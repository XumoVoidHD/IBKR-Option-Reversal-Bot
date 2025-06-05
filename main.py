from broker.ibkr_broker import IBTWSAPI
import creds
import asyncio
from ib_insync import *
import nest_asyncio
from datetime import datetime
from pytz import timezone
from discord_bot import send_discord_message
from logger import setup_logger

nest_asyncio.apply()

host_details = {
    "host": creds.host,
    "port": creds.port,
    "client_id": 14
}


class Strategy:

    def __init__(self):
        self.call_contract = None
        self.curr_CE_side = None
        self.call_stp_id = None
        self.put_stp_id = None
        self.atm_put_sl = None
        self.atm_call_sl = None
        self.atm_call_fill = None
        self.atm_put_fill = None
        self.broker = IBTWSAPI(creds=host_details)
        self.strikes = None
        self.call_percent = creds.call_sl
        self.put_percent = creds.put_sl
        self.call_buy_rentry = 0
        self.call_sell_rentry = 0
        self.testing = True
        self.reset = False
        self.func_test = False
        self.enable_logging = creds.enable_logging
        self.logger = setup_logger() if self.enable_logging else None

    async def dprint(self, phrase):
        print(phrase)
        if self.enable_logging:
            self.logger.info(phrase)
        await send_discord_message(phrase)

    async def lprint(self, phrase):
        if self.enable_logging:
            self.logger.info(phrase)

    async def get_closest_price(self, price: int) -> int:
        return min(self.strikes, key=lambda x: abs(x - price))

    async def get_current_price(self) -> int:
        current_price = await self.broker.current_price(creds.instrument, creds.exchange)
        return int(current_price)

    async def place_order(self, side: str, type: str, strike: int, quantity: int):
        self.call_contract = Option(
            symbol=creds.instrument,
            lastTradeDateOrContractMonth=creds.date,
            strike=strike,
            right=type.upper(),
            exchange=creds.exchange.upper(),
            currency="USD",
            multiplier='100'
        )
        try:
            k = await self.broker.place_market_order(contract=self.call_contract, qty=quantity, side=side.upper())
            fill_price = k[1]
            self.atm_call_sl = fill_price * (1 + (self.call_percent / 100))
            await self.dprint(f"Placing Order: {self.call_contract}")
            await self.dprint(f"Call Order sl is {self.atm_call_sl}")
        except Exception as e:
            await self.dprint(f"Error in placing order: {str(e)}, Contract: {self.call_contract}")

    async def place_call_order(self, side: str):
        current_price = await self.get_current_price()
        leg_target_price = current_price + (creds.strike_interval * creds.ATM_CALL)
        hedge_target_price = current_price + (creds.strike_interval * creds.OTM_CALL_HEDGE)
        closest_leg_price = await self.get_closest_price(leg_target_price)
        closest_hedge_price = await self.get_closest_price(hedge_target_price)
        hedge_side = "BUY" if side.upper() == "SELL" else "SELL"

        if creds.close_hedges:
            await self.place_order(side=hedge_side.upper(), type="C", strike=closest_hedge_price,
                                   quantity=creds.call_hedge_quantity)
            await self.dprint("Call Hedge Placed")

        await self.place_order(side=side.upper(), type="C", strike=closest_leg_price, quantity=creds.call_position)

        temp_percentage = 1
        if creds.STP_enabled:
            call_stp_id = await self.broker.place_stp_order(contract=self.call_contract, side="BUY",
                                                            quantity=creds.call_position,
                                                            sl=self.atm_call_sl)
            while True:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=creds.instrument,
                    expiry=creds.date,
                    strike=leg_target_price,
                    right="C"
                )

                if premium_price['ask'] <= self.atm_call_fill - temp_percentage * (
                        creds.call_entry_price_changes_by / 100) * self.atm_call_fill:
                    self.atm_call_sl = self.atm_call_sl - (self.atm_call_fill * (creds.call_change_sl_by / 100))
                    await self.dprint(
                        f"[CAL] Price dip detected - Adjusting trailing parameters"
                        f"\nFill Price: {self.atm_call_fill}"
                        f"\nCurrent Premium: {premium_price['ask']}"
                        f"\nNew SL: {self.atm_call_sl}"
                        f"\nTemp value: {temp_percentage}"
                    )
                    await self.broker.modify_stp_order(contract=self.call_contract, side="BUY",
                                                       quantity=creds.call_position, sl=self.atm_call_sl,
                                                       order_id=call_stp_id)
                    temp_percentage += 1
                    continue

                open_trades = await self.broker.get_positions()

                call_exists = any(
                    trade.contract.secType == 'OPT' and trade.contract.right == 'C' and
                    trade.contract.symbol == creds.instrument and trade.contract.strike == closest_leg_price
                    for trade in open_trades
                )

                if not call_exists:
                    if creds.close_hedges:
                        hedge_side = "BUY" if hedge_side.upper() == "SELL" else "SELL"
                        await self.place_order(side=hedge_side.upper(), type="C", strike=closest_hedge_price,
                                               quantity=creds.call_hedge_quantity)

                        await self.dprint(
                            f"[CALL {side.upper()}] Stop loss triggered"
                            f"\nCurrent Premium: {premium_price['mid']}"
                            f"\nStop Loss Level: {self.atm_call_sl}"
                            f"\nStrike Price: {leg_target_price}"
                            f"\nPosition Size: {creds.call_position}"
                        )
                        await self.call_side_handler()
                        return
        else:
            while True:
                return

    async def call_side_handler(self):
        if self.curr_CE_side == "SELL":
            await self.place_call_order("BUY")
            self.curr_CE_side = "BUY"
        else:
            await self.place_call_order("SELL")
            self.curr_CE_side = "SELL"

    async def main(self):
        await send_discord_message("." * 100)
        await self.dprint("\n1. Testing connection...")
        await self.broker.connect()
        await self.dprint(f"Connection status: {self.broker.is_connected()}")
        self.strikes = await self.broker.fetch_strikes(creds.instrument, creds.exchange,
                                                       secType="IND")
        if self.reset:
            # await self.close_all_positions(test=True)
            return

        if self.func_test:
            await self.broker.cancel_hedge()
            return

        while True:
            current_time = datetime.now(timezone('US/Eastern'))
            start_time = current_time.replace(
                hour=creds.entry_hour,
                minute=creds.entry_minute,
                second=creds.entry_second,
                microsecond=0)
            closing_time = current_time.replace(
                hour=creds.exit_hour,
                minute=creds.exit_minute,
                second=creds.exit_second,
                microsecond=0)
            await self.dprint(f"Current Time: {current_time}")
            if (start_time <= current_time <= closing_time) or self.testing:
                await self.call_side_handler()


if __name__ == "__main__":
    s = Strategy()
    asyncio.run(s.main())
