#!/usr/bin/python3
#
# MoneybirdPaypalFetcher.py
# (C) 2021 - FO
#
import sys
from datetime import datetime,timedelta
import configparser
import requests
import json

##################################################
# Functions
##################################################

####################################
# Paypal
#
def pp_oauth():
    clientid = config.get('paypal', 'clientid')
    secret = config.get('paypal', 'secret')
    
    url = config.get('paypal', 'endpoint') + '/v1/oauth2/token'
    headers = {
        'Accept': 'application/json',
        'Accept-Language': 'en_US',
    }
    data = {
       'grant_type': 'client_credentials',
    }
    response = requests.post(url, headers=headers, data=data, auth=(clientid, secret))
    if response.status_code == requests.codes.ok:
        pp_json = response.json()
        return pp_json["access_token"]
    else:
        pp_json = response.json()
        print("ERROR: pp_oauth: ", pp_json["error_description"])
        sys.exit()

def pp_gettransactions(token, start_date, end_date):
    # @@@TODO@@@ Pagination of results in case of large result sets is not handled!
    url = config.get('paypal', 'endpoint') + '/v1/reporting/transactions'

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer '+token,
    }
    params = {
       'start_date': start_date,
       'end_date': end_date,
       'balance_affecting_records_only': 'N',
       'fields': 'all',
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == requests.codes.ok:
        pp_transactions = response.json()
        transactions = {}
        for pp_transaction in pp_transactions["transaction_details"]:
            # Breaking down the transaction log. Each transaction consists of:
            pp_transaction_info = pp_transaction["transaction_info"]
            payer_info = pp_transaction["payer_info"]
            
            # https://developer.paypal.com/docs/integration/direct/transaction-search/transaction-event-codes/
            transaction_event_code = pp_transaction_info["transaction_event_code"]
            if("T00" in transaction_event_code):
                # Website payment transaction (but unsure if sent or received!)
                tr_id = pp_transaction_info["transaction_id"]
                transactions[tr_id] = {}
                transactions[tr_id]["date"] = pp_transaction_info["transaction_initiation_date"]
                # Register who is the other party in this transaction
                message = payer_info["email_address"]+" "+payer_info["payer_name"]["alternate_full_name"]
                # Register what the transaction is for
                if("invoice_id" in pp_transaction_info):
                    message = message + " " + pp_transaction_info["invoice_id"]
                if("custom_field" in pp_transaction_info):
                    message = message + " " + pp_transaction_info["custom_field"]
                # Register the original currency and value
                message = message + " (" + pp_transaction_info["transaction_amount"]["currency_code"] + " " + pp_transaction_info["transaction_amount"]["value"] + ")"
                if (pp_transaction_info["transaction_amount"]["currency_code"] == "EUR"):
                    transactions[tr_id]["eur_amount"] = float(pp_transaction_info["transaction_amount"]["value"])
                if (pp_transaction_info["transaction_amount"]["currency_code"] == "USD"):
                    transactions[tr_id]["usd_amount"] = float(pp_transaction_info["transaction_amount"]["value"])
                # Mark transaction updates explicitly
                if (pp_transaction_info["transaction_updated_date"] != pp_transaction_info["transaction_initiation_date"]):
                    message = message + " - TRANSACTION UPDATE MARKER"
                    transactions[tr_id]["usd_amount"] = 0
                    transactions[tr_id]["eur_amount"] = 0
                    transactions[tr_id]["date"] = pp_transaction_info["transaction_updated_date"]
                    print("WARNING: Transaction got updated, please check if we did the right thing!")
                # Push message
                transactions[tr_id]["message"] = message

                # If fee_amount is set, then create an additional transaction line
                if("fee_amount" in pp_transaction_info):
                    fee_id = tr_id+"fee"
                    transactions[fee_id] = {}
                    transactions[fee_id]["date"] = pp_transaction_info["transaction_initiation_date"]
                    feemessage = "Paypal transaction fee"
                    feemessage = feemessage + " (" + pp_transaction_info["fee_amount"]["currency_code"] + " " + pp_transaction_info["fee_amount"]["value"] + ")"
                    transactions[fee_id]["message"] = feemessage
                    if (pp_transaction_info["fee_amount"]["currency_code"] == "EUR"):
                        transactions[fee_id]["eur_amount"] = float(pp_transaction_info["fee_amount"]["value"])
                    if (pp_transaction_info["fee_amount"]["currency_code"] == "USD"):
                        transactions[fee_id]["usd_amount"] = float(pp_transaction_info["fee_amount"]["value"])

            elif("T02" in transaction_event_code):
                # Currency conversion
                tr_id = pp_transaction_info["paypal_reference_id"]
                if(pp_transaction_info["transaction_amount"]["currency_code"] == "USD"):
                    if("usd_amount" in transactions[tr_id]):
                        transactions[tr_id]["usd_amount"] = transactions[tr_id]["usd_amount"] + float(pp_transaction_info["transaction_amount"]["value"])
                    else:
                        transactions[tr_id]["usd_amount"] = float(pp_transaction_info["transaction_amount"]["value"])
                if(pp_transaction_info["transaction_amount"]["currency_code"] == "EUR"):
                    if("eur_amount" in transactions[tr_id]):
                        transactions[tr_id]["eur_amount"] = transactions[tr_id]["eur_amount"] + float(pp_transaction_info["transaction_amount"]["value"])
                    else:
                        transactions[tr_id]["eur_amount"] = float(pp_transaction_info["transaction_amount"]["value"])

            elif("T03" in transaction_event_code):
                # Bank deposit into Paypal account
                tr_id = pp_transaction_info["transaction_id"]
                transactions[tr_id] = {}
                transactions[tr_id]["date"] = pp_transaction_info["transaction_initiation_date"]
                message = "Bank to Paypal"
                message = message + " " + pp_transaction_info.get("bank_reference_id", "(no ref)")
                # Register the original currency and value
                message = message + " (" + pp_transaction_info["transaction_amount"]["currency_code"] + " " + pp_transaction_info["transaction_amount"]["value"] + ")"
                transactions[tr_id]["message"] = message
                if (pp_transaction_info["transaction_amount"]["currency_code"] == "EUR"):
                    transactions[tr_id]["eur_amount"] = float(pp_transaction_info["transaction_amount"]["value"])
                if (pp_transaction_info["transaction_amount"]["currency_code"] == "USD"):
                    transactions[tr_id]["usd_amount"] = float(pp_transaction_info["transaction_amount"]["value"])

            else:
                print("WARNING: Unhandled code", transaction_event_code)

            # build up a consolidated transaction blob
            if("paypal_reference_id" in pp_transaction_info):
                tr_id = pp_transaction_info["paypal_reference_id"]
                # but overwrite that in some scenario's
                if("transaction_event_code" in pp_transaction_info and "T03" in pp_transaction_info["transaction_event_code"]):
                    # Bank transactions are singled out
                    tr_id = pp_transaction_info["transaction_id"]
            else:
                tr_id = pp_transaction_info["transaction_id"]

            transaction_date = pp_transaction_info["transaction_initiation_date"]
        print("INFO: Found " + str(len(transactions)) + " transactions")
        return transactions

    else:
        print("ERROR: pp_gettransactions dumps: ", response.text)
        sys.exit()


#
# Moneybird
#
def mb_oauth():
    clientid = config.get('moneybird', 'clientid')
    secret = config.get('moneybird', 'secret')
    token = config.get('moneybird', 'token')

    return token  # I've created a personal API token, which does not need a lot of OAuth2 stuff.

    #####################################
    # below here is only for external app stuff @@@TODO@@@ This can be used to make it more generic.

    # Fetch bearer token
    url = config.get('moneybird', 'endpoint') + '/oauth/token'

    headers = {
        'Accept': 'application/json',
        'Accept-Language': 'en_US',
    }
    data = {
       'grant_type': 'authorization_code',
       'client_id': clientid,
       'client_secret': secret,
       'code': token,
       'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
    }
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == requests.codes.ok:
        print("INFO: mb_oauth login succeeded")
        mb_json = response.json()
        return mb_json["access_token"]
    else:
        mb_json = response.json()
        if(mb_json["error"] == "invalid_grant"):
            print("ERROR: mb_oauth has invalid grants, maybe try to log in again?")

            # Display an authorization link
            url = config.get('moneybird', 'endpoint') + '/oauth/authorize'
            params = {
               'response_type': 'code',
               'client_id': clientid,
               'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
            }
            response = requests.get(url, params=params)
            print("Please visit the URL below and update the token in MoneybirdPaypalFetcher.ini as appropriate")
            print(response.url)
        else:
            print("ERROR: mb_oauth: ", mb_json["error_description"])
        sys.exit()


def mb_getfinacct(token, name):
    adminid = config.get('moneybird', 'adminid')
    finacct = config.get('moneybird', 'finacct')
    url = config.get('moneybird', 'endpoint') + '/api/v2/' + adminid + '/financial_accounts.json'

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer '+token,
    }
    response = requests.get(url, headers=headers)
    accounts = response.json()
    finacctid = 0
    for account in accounts:
        if(account["identifier"] == finacct):
            finacctid = int(account["id"])
    if(finacctid == 0):
        print("ERROR: mb_getfinacct cannot identify the right financial account id")
        sys.exit()
    else:
        print("INFO: mb_getfinacct found "+finacct)
        return finacctid


def mb_createstatement(token, transactions):
    adminid = config.get('moneybird', 'adminid')
    finacctid = mb_getfinacct(token, config.get('moneybird', 'adminid'))


    # Statement reference
    refdate = datetime.now()
    ref = "PaypalFetcher import " + refdate.strftime("%Y-%m-%d %H:%M:%S")
    # Construct the Moneybird format for a financial statement header
    statement = {}
    statement["financial_statement"] = {}
    statement["financial_statement"]["financial_account_id"] = finacctid
    statement["financial_statement"]["reference"] = ref
    statement["financial_statement"]["financial_mutations_attributes"] = {}
    
    # Append the transaction lines
    t = 1
    for transaction in transactions:
        transactiondate = datetime.strptime(transactions[transaction]["date"], "%Y-%m-%dT%H:%M:%S%z")
        statement["financial_statement"]["financial_mutations_attributes"][t] = {}
        statement["financial_statement"]["financial_mutations_attributes"][t]["date"] = transactiondate.strftime("%Y-%m-%d")
        statement["financial_statement"]["financial_mutations_attributes"][t]["message"] = transactions[transaction]["message"]
        statement["financial_statement"]["financial_mutations_attributes"][t]["amount"] = transactions[transaction]["eur_amount"]
        t = t+1

    print("INFO: Ready to submit", ref)

    # Submit the statement
    url = config.get('moneybird', 'endpoint') + '/api/v2/' + adminid + '/financial_statements.json'

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer '+token,
    }
    data = json.dumps(statement)

    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 201:
        print("INFO: mb_createstatement succeeded")
    else:
        print("INFO: mb_createstatement failed")
        print(response.text)


##################################################
# Main program
##################################################
# Variables
version = 1
# Read config if available
config = configparser.ConfigParser()
config.read('MoneybirdPaypalFetcher.ini')

quiet = config.get('general', 'quiet', fallback='false')
# Print program banner
print("MoneybirdPaypalFetcher v", version)
print("")

# Log in to Moneybird
mb_token = mb_oauth()

# Log in to Paypal
pp_token = pp_oauth()

# Fetch transactions from yesterday
enddate = datetime.today()
startdate = enddate - timedelta(days = 1)
enddatestring = enddate.strftime("%Y-%m-%d") + "T00:00:00Z"
startdatestring = startdate.strftime("%Y-%m-%d") + "T00:00:00Z"
print("INFO: Looking for transactions between "+startdatestring+" and "+enddatestring)

pp_transactions = pp_gettransactions(pp_token, startdatestring, enddatestring)

if(len(pp_transactions) > 0):
    mb_createstatement(mb_token, pp_transactions)
else:
    print("INFO: No transactions inside window, nothing to do")

print("INFO: Finished")
