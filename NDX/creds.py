# Default Values
port = 7497
host = "127.0.0.1"
instrument = "NDX"
exchange = "SMART"
currency = "USD"
strike_interval = 10
enable_logging = True
WEBHOOK_URL = "https://discord.com/api/webhooks/1381257758640443565/Ln5AGYBpU59q0b56jkvIlMGfuXXnrC15dNiVNtCG4rfjzOwZ_WA9K3GJsgFDFgD94G_8"

# Global Values
date = "20250617"                # Date of contract (YYYY-MM-DD)
entry_hour = 9                      # Entry time in hours
entry_minute = 30                   # Entry time in minutes
entry_second = 59                    # Entry time in seconds
exit_hour = 16                     # Exit time in hours
exit_minute = 30                    # Exit time in minutes
exit_second = 00                     # Exit time in seconds
call_check_time = 1
put_check_time = 1

#Hedges
OTM_CALL_HEDGE = 10                # How far away the call hedge is (10 means that its $50 away from current price)
OTM_PUT_HEDGE = 10                 # How far away the put hedge is (10 means that its $50 away from current price)
close_hedges = False
active_close_hedges = True
# if active_close_hedges is false then don't open the hedges at all if true
# And close_hedges is true then close and open hedges accordingly
# And if close-hedges is False then just open the hedges but don't close them
call_hedge_quantity = 1             # Quantity for call hedge
put_hedge_quantity = 1              # Quantity for put hedge

#SELL SIDE
CE_SELL_REENTRY = 2
PE_SELL_REENTRY = 1
ATM_CALL_SELL = 5                       # How far away call position is (2 means that its $10 away from current price)
ATM_PUT_SELL = 5
call_sl_sell = 30
put_sl_sell = 30
sell_put_entry_price_changes_by = 10      # What % should put entry premium price should change by to update the trailing %
sell_put_change_sl_by = 10                # What % of entry price should put sl change when trailing stop loss updates
sell_call_entry_price_changes_by = 10     # What % should call entry premium price should change by to update the trailing %
sell_call_change_sl_by = 10               # What % of entry price should call sl change when trailing stop loss updates
sell_call_position_quantity = 1                   # Quantity for call position
sell_put_position_quantity = 1                    # Quantity for put position

#BUY SIDE
CE_BUY_REENTRY = 2
PE_BUY_REENTRY = 1
ATM_CALL_BUY = 5                       # How far away call position is (2 means that its $10 away from current price)
ATM_PUT_BUY = 5                         # How far away put position is (2 means that its $10 away from current price)
call_sl_buy = 30                            # From where the call stop loss should start from (15 here means 15% of entry price)
put_sl_buy = 30                         # From where the put stop loss should start from (15 here means 15% of entry price)
buy_put_entry_price_changes_by = 10      # What % should put entry premium price should change by to update the trailing %
buy_put_change_sl_by = 10                # What % of entry price should put sl change when trailing stop loss updates
buy_call_entry_price_changes_by = 10     # What % should call entry premium price should change by to update the trailing %
buy_call_change_sl_by = 10               # What % of entry price should call sl change when trailing stop loss updates
buy_call_position_quantity = 1                   # Quantity for call position
buy_put_position_quantity = 1                    # Quantity for put position