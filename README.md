# MoneybirdPaypalFetcher

WARNING: HERE BE DRAGONS!

A quick and hacky script to import paypal transactions (business account) and import them to Moneybird as a financial statement. Script can be run from cron on a daily basis.

The script does an attempt to consolidate some lines, and expand on some other. Cases handled:

* If you pay something in USD and get currency conversion to EUR, these are 'flattened' in to the parent transaction
* If you receive funds and Paypal adds a fee, this fee is extracted in to a new transaction so you can book it under costs

