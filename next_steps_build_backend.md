# Next steps: build backend for Resources + Building Requests

## Implement backend functions in app.py
1. `apply_resource_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, tree_amount, metal_amount, food_amount, acting_user, description)`
   - validate: amount > 0, from != to
   - permissions: emperor always; king/graf can only transfer from own kingdom (by kingdom_name)
   - validate balances on from kingdom for each resource
   - update balances: subtract from from kingdom, add to to kingdom
   - insert `reports` for to_kingdom with report_type = 'Ресурсы: перевод'
   - insert into `transactions` (optional)

2. `submit_building_request(db, county_id, item_name, requested_tree_cost, requested_metal_cost, requested_food_cost, requested_kingdom_cash_cost, treasury_cash_covered_requested, proposed_daily_income_tree, proposed_daily_income_metal, proposed_daily_income_food, acting_user, reason)`
   - find county + kingdom
   - permissions:
     - graf can submit only for counties assigned to them (graf_user_id)
     - king can submit for all counties in his kingdom (kingdom_name)
   - check kingdom budget >= kingdom_cash_cost
   - check treasury >= treasury_cash_covered
   - check kingdom resources >= requested costs
   - create building_requests row with status='submitted'
   - insert report for kingdom

3. `approve_building_request(db, request_id, emperor_treasury_cover, approved_by_username, proposed_income_tree, proposed_income_metal, proposed_income_food, reason)`
   - permissions: emperor only
   - load request + kingdom + county
   - verify not already approved/rejected
   - check resources/costs again
   - update kingdom budget: kingdom_cash_cost subtract
   - update settings treasury subtract treasury_cash_covered
   - update kingdom resources subtract costs; do not add back
   - set request status='approved', approved fields
   - apply daily income after building: kingdom.tree_income += proposed_income_tree, etc.
   - insert report for kingdom with report_type='Постройка: одобрено'

## Implement endpoints
- POST `/resources/transfer`
- POST `/build_requests/submit`
- POST `/build_requests/approve`

Each endpoint must:
- call corresponding backend function
- commit
- call `send_report_to_telegram()` after every POST
- flash success/error

## Add UI templates later
- templates/resources.html
- templates/build_requests.html

