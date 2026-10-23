# Logistics cancellation refunds

New cancellation settlements automatically credit the cancelled Parcel's original
price before tax, less the business's fixed cancellation service charge. Original tax is
retained in full. A price of 100 plus 10 tax produces a credit of 100; a service
charge of 15 reduces that credit to 85. Owners and admins configure the charge
in **Business Settings → Invoice defaults → Cancellation service charge per
parcel**, in the business's currency. It defaults to zero. The cancellation form
has no editable fee: the server calculates it automatically from this setting.
This setting is shown for Logistics businesses; SERVICE settings are unchanged.

The calculation uses saved Invoice amounts and the Parcel's original financial
allocation, including tax rounding. Current catalog prices and workspace tax
defaults do not change it. Shared freight still requires explicit original
Parcel and receipt allocations when these have not already been recorded.
The service charge is applied once per cancelled Parcel across its original
charges and Invoices, capped at the combined price before tax. A nonzero charge
requires original obligations in the configured business currency; currency
differences require accounting reconciliation. No currency conversion occurs.

The credit reduces the obligation. The actual refund due is the excess of
recorded net payments over the remaining obligation, so an unpaid Parcel does
not generate a refund. For example, 40 paid against 100 plus 10 tax produces a
refund due of 30 with no service charge. If less than the retained amount has
been paid, the remainder stays outstanding.

The preview shows recorded net payments and warns when no customer payment is
recorded. If the customer already paid, use **Record customer payment** before
confirming the cancellation, then preview again. A 105 price with zero tax and
zero service charge gives a 105 credit; it gives a 105 cash refund due once the
original 105 payment has been recorded. Recording that payment invalidates the
earlier preview, so confirmation requires a fresh review.

Accounting previews and confirms the settlement before credits are recorded.
For a Parcel whose original allocations are already known, opening the
cancellation page automatically shows the calculation. A cancellation reason
and a fresh confirmation are still required before financial records change.
The completed-refund form prefills the available amount when one credited
obligation is eligible, or the Parcel's refund link identifies it. Returning money remains manual, and recording the
settlement does not record a completed refund. Existing confirmed settlements,
including their historical tax credits, are preserved. Previews created under
the previous policy must be reviewed again before confirmation. Changing the
global fee or its currency after preview also requires a fresh review. Confirmed
settlements snapshot the configured and applied fee and keep their saved amounts.

`businesses.0033_business_cancellation_service_charge` adds the zero-default
setting and a nonnegative database constraint. It does not change Invoice,
payment or historical settlement amounts.
