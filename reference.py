from broker.ibkr_broker import IBTWSAPI
import creds as credentials
import asyncio
from ib_insync import *
import nest_asyncio
from datetime import datetime
from pytz import timezone
from discord_bot import send_discord_message
from logger import setup_logger


nest_asyncio.apply()

host_details = {
    "host": credentials.host,
    "port": credentials.port,
    "client_id": 14
}


class Strategy:

    def __init__(self):
        self.call_contract = None
        self.put_contract = None
        self.call_stp_id = None
        self.put_stp_id = None
        self.atm_put_sl = None
        self.atm_call_sl = None
        self.atm_call_fill = None
        self.atm_put_fill = None
        self.otm_closest_call = credentials.call_hedge
        self.otm_closest_put = credentials.put_hedge
        self.call_target_price = credentials.call_strike
        self.put_target_price = credentials.put_strike
        self.broker = IBTWSAPI(creds=host_details)
        self.strikes = None
        self.call_percent = credentials.call_sl
        self.put_percent = credentials.put_sl
        self.call_rentry = 0
        self.put_rentry = 0
        self.call_order_placed = False
        self.put_order_placed = False
        self.should_continue = True
        self.testing = True
        self.reset = False
        self.func_test = False
        self.enable_logging = credentials.enable_logging
        self.logger = setup_logger() if self.enable_logging else None

    async def dprint(self, phrase):
        print(phrase)
        if self.enable_logging:
            self.logger.info(phrase)
        # await send_discord_message(phrase)

    async def lprint(self,phrase):
        if self.enable_logging:
            self.logger.info(phrase)

    async def main(self):
        await send_discord_message("." * 100)
        await self.dprint("\n1. Testing connection...")
        await self.broker.connect()
        await self.dprint(f"Connection status: {self.broker.is_connected()}")

        if self.reset:
            await self.close_all_positions(test=True)
            return

        if self.func_test:
            await self.broker.cancel_hedge()
            return

        while True:
            current_time = datetime.now(timezone('US/Eastern'))
            start_time = current_time.replace(
                hour=credentials.entry_hour,
                minute=credentials.entry_minute,
                second=credentials.entry_second,
                microsecond=0)
            closing_time = current_time.replace(
                hour=credentials.exit_hour,
                minute=credentials.exit_minute,
                second=credentials.exit_second,
                microsecond=0)
            await self.dprint(f"Current Time: {current_time}")
            if (start_time <= current_time <= closing_time) or self.testing:
                self.strikes = await self.broker.fetch_strikes(credentials.instrument, credentials.exchange,
                                                               secType="IND")
                current_price = await self.broker.current_price(credentials.instrument, credentials.exchange)
                current_price = int(current_price)

                closest_strike = min(self.strikes, key=lambda x: abs(x - current_price))

                await self.dprint("\n\nNew Trading Session Start\n")
                await self.dprint(f"CURRENT PRICE: {current_price}")

                await self.dprint(f"CLOSEST CURRENT PRICE: {closest_strike}")

                if credentials.calc_values:
                    self.otm_closest_call = closest_strike + (credentials.OTM_CALL_HEDGE * 5)
                await self.dprint(f"CALL HEDGE STRIKE PRICE: {self.otm_closest_call}")

                if credentials.calc_values:
                    self.otm_closest_put = closest_strike - (credentials.OTM_PUT_HEDGE * 5)
                await self.dprint(f"PUT HEDGE STRIKE PRICE: {self.otm_closest_put}")

                if credentials.calc_values:
                    self.call_target_price = closest_strike
                    if credentials.ATM_CALL > 0:
                        self.call_target_price += 5 * credentials.ATM_CALL
                await self.dprint(f"CALL POSITION STRIKE PRICE: {self.call_target_price}")

                if credentials.calc_values:
                    self.put_target_price = closest_strike
                    if credentials.ATM_CALL > 0:
                        self.put_target_price -= 5 * credentials.ATM_CALL
                await self.dprint(f"PUT POSITION STRIKE PRICE: {self.put_target_price}")
                await self.place_hedge_orders(call=True, put=True)
                await self.place_atm_put_order()
                await self.place_atm_call_order()
                break
            else:
                await self.dprint("Market hasn't opened yet")
            await asyncio.sleep(10)

        await asyncio.gather(
            self.call_trail_check(),
            self.close_all_positions(test=False),
            self.put_trail_check(),
            self.put_hedge_check(),
            self.call_hedge_check(),
        )

    async def close_all_positions(self, test):
        if credentials.close_positions and not test:
            return
        else:
            while True:
                current_time = datetime.now(timezone('US/Eastern'))
                target_time = current_time.replace(
                    hour=credentials.exit_hour,
                    minute=credentials.exit_minute,
                    second=credentials.exit_second,
                    microsecond=0)

                if current_time >= target_time or test:
                    self.should_continue = False
                    await self.broker.close_all_open_orders()
                    try:
                        await asyncio.gather(
                            self.close_call(),
                            self.close_put(),
                        )
                        await self.dprint("All position closed")
                    except Exception as e:
                        await self.dprint(e)
                    break

                await asyncio.sleep(10)

    async def close_call(self):
        if self.call_order_placed:
            await self.broker.cancel_call(hedge_strike=self.otm_closest_call, position_strike=self.call_target_price,
                                          close_hedge=credentials.close_hedges)
        else:
            return

    async def close_put(self):
        if self.put_order_placed:
            await self.broker.cancel_put(hedge_strike=self.otm_closest_put, position_strike=self.put_target_price,
                                         close_hedge=credentials.close_hedges)
        else:
            return

    async def place_hedge_orders(self, call, put):
        if call:
            spx_contract_call = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_call,
                right='C',
                exchange="SMART",
                currency="USD",
                multiplier='100'
            )
            try:
                await self.broker.place_market_order(contract=spx_contract_call,
                                                     qty=credentials.call_hedge_quantity, side="BUY")
                await self.dprint("Placing Hedge Call Order")
            except Exception as e:
                await self.dprint(f"Error placing call hedge order: {str(e)}")

        if put:
            spx_contract_put = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_put,
                right='P',
                exchange="SMART",
                currency="USD",
                multiplier='100'
            )
            try:
                await self.broker.place_market_order(contract=spx_contract_put, qty=credentials.put_hedge_quantity,
                                                     side="BUY")
                await self.dprint("Placing Hedge Put Order")
            except Exception as e:
                await self.dprint(f"Error placing put hedge order: {str(e)}")

    async def close_open_hedges(self, close_put=False, close_call=False):
        if close_call:
            spx_contract_call = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_call,
                right='C',
                exchange="SMART",
                currency="USD",
                multiplier='100'
            )
            try:
                await self.broker.place_market_order(contract=spx_contract_call, qty=credentials.call_hedge_quantity,
                                                     side="SELL")
                await self.dprint("Closing Call Hedge")
            except Exception as e:
                await self.dprint(f"Error closing call hedge: {str(e)}")

        if close_put:
            spx_contract_put = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_put,
                right='P',
                exchange="SMART",
                currency="USD",
                multiplier='100'
            )
            try:
                await self.broker.place_market_order(contract=spx_contract_put, qty=credentials.put_hedge_quantity,
                                                     side="SELL")
                await self.dprint("Closing Put Hedge")
            except Exception as e:
                await self.dprint(f"Error closing put hedge: {str(e)}")

    async def place_atm_call_order(self):
        premium_price = await self.broker.get_latest_premium_price(
            symbol=credentials.instrument,
            expiry=credentials.date,
            strike=self.call_target_price,
            right="C"
        )
        self.call_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=self.call_target_price,
            right='C',
            exchange="SMART",
            currency="USD",
            multiplier='100'
        )

        qualified_contracts = self.broker.client.qualifyContracts(self.call_contract)
        if not qualified_contracts:
            raise ValueError("Failed to qualify contract with IBKR.")
        print('last price is', premium_price['last'])

        try:
            k = await self.broker.place_market_order(contract=self.call_contract, qty=credentials.call_position,
                                                     side="SELL")
            self.call_order_placed = True
            self.atm_call_fill = k[1]
            self.atm_call_sl = self.atm_call_fill * (1 + (self.call_percent / 100))
            await self.dprint(f"Call Order placed at {k[1]}")
            await self.dprint(f"Call Order sl is {self.atm_call_sl}")
            await asyncio.sleep(1)
            self.call_stp_id = await self.broker.place_stp_order(contract=self.call_contract, side="BUY",
                                                                 quantity=credentials.call_position,
                                                                 sl=self.atm_call_sl)
        except Exception as e:
            await self.dprint(f"Error in placing sell side call order: {str(e)}")

    async def call_hedge_check(self):
        while self.should_continue:
            if self.call_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Hedge Premium: {premium_price}")
                open_trades = await self.broker.get_positions()

                call_exists = any(
                    trade.contract.secType == 'OPT' and trade.contract.right == 'C' and
                    trade.contract.symbol == credentials.instrument and trade.contract.strike == self.call_target_price
                    for trade in open_trades
                )

                if not call_exists and self.should_continue:
                    self.call_order_placed = False
                    if credentials.close_hedges:
                        await self.close_open_hedges(close_call=True, close_put=False)
                    await self.dprint(
                        f"[CALL] Stop loss triggered - Executing market buy"
                        f"\nCurrent Premium: {premium_price['mid']}"
                        f"\nStop Loss Level: {self.atm_call_sl}"
                        f"\nStrike Price: {self.call_target_price}"
                        f"\nPosition Size: {credentials.call_position}"
                    )
                    continue

            await asyncio.sleep(1)

    async def call_trail_check(self):
        temp_percentage = 1
        while self.should_continue:
            if self.call_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Sell Leg Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_call_fill - temp_percentage * (
                        credentials.call_entry_price_changes_by / 100) * self.atm_call_fill:
                    self.atm_call_sl = self.atm_call_sl - (self.atm_call_fill * (credentials.call_change_sl_by / 100))
                    await self.dprint(
                        f"[CALL] Price dip detected - Adjusting trailing parameters"
                        f"\nFill Price: {self.atm_call_fill}"
                        f"\nCurrent Premium: {premium_price['ask']}"
                        f"\nNew SL: {self.atm_put_sl}"
                        f"\nTemp value: {temp_percentage}"
                    )
                    await self.broker.modify_stp_order(contract=self.call_contract, side="BUY",
                                                       quantity=credentials.call_position, sl=self.atm_call_sl,
                                                       order_id=self.call_stp_id)
                    temp_percentage += 1

                await asyncio.sleep(credentials.call_check_time)
            else:
                await self.dprint("Checking for call re-entry")
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Sell Leg Re-entry Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_call_fill and self.call_rentry < credentials.number_of_re_entry:
                    await self.dprint(
                        f"[CALL] Entry condition met - Initiating new position"
                        f"\nCurrent Premium: {premium_price['bid']}"
                        f"\nEntry Price: {self.atm_call_fill}"
                        f"\nStrike Price: {self.call_target_price}"
                        f"\nReentry Count: {self.call_rentry + 1}"
                    )
                    self.call_rentry += 1
                    await self.dprint(f"Number of re-entries happened: {self.call_rentry}")
                    if credentials.close_hedges:
                        await self.place_hedge_orders(call=True, put=False)
                    await self.place_atm_call_order()
                    temp_percentage = 1
                    self.call_order_placed = True
                    continue

                if not self.call_rentry < credentials.number_of_re_entry:
                    await self.dprint("Call re-entry limit reached")
                    return

                await asyncio.sleep(credentials.call_reentry_time)

    async def place_atm_put_order(self):
        premium_price = await self.broker.get_latest_premium_price(
            symbol=credentials.instrument,
            expiry=credentials.date,
            strike=self.put_target_price,
            right="P"
        )
        self.put_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=self.put_target_price,
            right='P',
            exchange="SMART",
            currency="USD",
            multiplier='100'
        )

        qualified_contracts = self.broker.client.qualifyContracts(self.put_contract)
        if not qualified_contracts:
            raise ValueError("Failed to qualify contract with IBKR.")
        print('last price is', premium_price['last'])

        try:
            k = await self.broker.place_market_order(contract=self.put_contract, qty=credentials.put_position,
                                                     side="SELL")
            self.put_order_placed = True
            self.atm_put_fill = k[1]
            self.atm_put_sl = self.atm_put_fill * (1 + (self.put_percent / 100))
            await self.dprint(f"Put Order placed at {k[1]}")
            await self.dprint(f"Put Order sl is {self.atm_put_sl}")
            await asyncio.sleep(1)
            self.put_stp_id = await self.broker.place_stp_order(contract=self.put_contract, side="BUY",
                                                                quantity=credentials.put_position,
                                                                sl=self.atm_put_sl)
        except Exception as e:
            await self.dprint(f"Error in placing sell side put order: {str(e)}")

    async def put_hedge_check(self):
        while self.should_continue:
            if self.put_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Hedge Premium: {premium_price}")
                open_trades = await self.broker.get_positions()

                put_exists = any(
                    trade.contract.secType == 'OPT' and trade.contract.right == 'P' and
                    trade.contract.symbol == credentials.instrument and trade.contract.strike == self.put_target_price
                    for trade in open_trades
                )

                if not put_exists and self.should_continue:
                    self.put_order_placed = False
                    if credentials.close_hedges:
                        await self.close_open_hedges(close_call=False, close_put=True)
                    await self.dprint(
                        f"[PUT] Stop loss triggered - Executing market buy"
                        f"\nCurrent Premium: {premium_price['mid']}"
                        f"\nStop Loss Level: {self.atm_put_sl}"
                        f"\nStrike Price: {self.put_target_price}"
                        f"\nPosition Size: {credentials.put_position}"
                    )
                    continue

            await asyncio.sleep(1)

    async def put_trail_check(self):
        temp_percentage = 1
        while self.should_continue:
            if self.put_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Sell Leg Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_put_fill - temp_percentage * (
                        credentials.put_entry_price_changes_by / 100) * self.atm_put_fill:
                    self.atm_put_sl = self.atm_put_sl - (self.atm_put_fill * (credentials.put_change_sl_by / 100))
                    await self.dprint(
                        f"[PUT] Price dip detected - Adjusting trailing parameters"
                        f"\nFill Price: {self.atm_put_fill}"
                        f"\nCurrent Premium: {premium_price['ask']}"
                        f"\nNew SL: {self.atm_put_sl}"
                        f"\nTemp value: {temp_percentage}"
                    )
                    await self.broker.modify_stp_order(contract=self.put_contract, side="BUY",
                                                       quantity=credentials.put_position, sl=self.atm_put_sl,
                                                       order_id=self.put_stp_id)
                    temp_percentage += 1

                await asyncio.sleep(credentials.put_check_time)
            else:
                await self.dprint("Checking for put re-entry")
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Sell Leg Re-entry Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_put_fill and self.put_rentry < credentials.number_of_re_entry:
                    await self.dprint(
                        f"[PUT] Entry condition met - Initiating new position"
                        f"\nCurrent Premium: {premium_price['bid']}"
                        f"\nEntry Price: {self.atm_put_fill}"
                        f"\nStrike Price: {self.put_target_price}"
                        f"\nReentry Count: {self.put_rentry + 1}"
                    )
                    self.put_rentry += 1
                    await self.dprint(f"Number of re-entries happened: {self.call_rentry}")
                    if credentials.close_hedges:
                        await self.place_hedge_orders(call=False, put=True)
                    await self.place_atm_put_order()
                    temp_percentage = 1
                    self.put_order_placed = True
                    continue

                if not self.put_rentry < credentials.number_of_re_entry:
                    await self.dprint("Put re-entry limit reached")
                    return

                await asyncio.sleep(credentials.put_reentry_time)


if __name__ == "__main__":
    s = Strategy()
    asyncio.run(s.main())
