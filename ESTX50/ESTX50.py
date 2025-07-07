from ibkr_broker import IBTWSAPI
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
    "client_id": 13
}


class Strategy:

    def __init__(self):
        self.otm_call_id = None
        self.otm_call_fill = None
        self.otm_put_id = None
        self.otm_put_fill = None
        self.atm_call_id = None
        self.atm_put_id = None
        self.PE_SELL_REENTRY = 0
        self.PE_BUY_REENTRY = 0
        self.CE_SELL_REENTRY = 0
        self.CE_BUY_REENTRY = 0
        self.call_continue = True
        self.should_continue = True
        self.put_contract = None
        self.call_contract = None
        self.curr_CE_side = "BUY"
        self.curr_PE_side = "BUY"
        self.atm_put_sl = None
        self.atm_call_sl = None
        self.atm_call_fill = None
        self.atm_put_fill = None
        self.broker = IBTWSAPI(creds=host_details)
        self.strikes = None
        self.call_buy_rentry = 0
        self.call_sell_rentry = 0
        self.testing = False
        self.reset = False
        self.func_test = True
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
        current_price = await self.broker.current_price(creds.instrument, "EUREX")
        return int(current_price)

    async def place_order(self, side: str, type: str, strike: int, quantity: int):
        contract = Option(
            symbol=creds.instrument,
            lastTradeDateOrContractMonth=creds.date,
            strike=strike,
            right=type.upper(),
            exchange=creds.exchange.upper(),
            currency="EUR",
            multiplier='10',
            tradingClass=creds.trading_class
        )

        try:
            k = await self.broker.place_market_order(contract=contract, qty=quantity, side=side.upper())
            fill = k[1]
            await self.dprint(
                f"Placing Order:"
                f"\nSymbol: {contract.symbol}"
                f"\nExpiry: {contract.lastTradeDateOrContractMonth}"
                f"\nStrike: {contract.strike}"
                f"\nRight: {contract.right}"
                f"\nExchange: {contract.exchange}"
                f"\nmCurrency: {contract.currency}"
                f"\nMultiplier: {contract.multiplier}")

            return contract, fill, k[2]
        except Exception as e:
            await self.dprint(f"Error in placing order: {str(e)}, Contract: {contract}")

    async def place_call_order(self, side: str):
        current_price = await self.get_current_price()
        closest_current_price = await self.get_closest_price(current_price)
        leg_target_price = 0
        if side == "SELL":
            leg_target_price = closest_current_price + (creds.strike_interval * creds.ATM_CALL_SELL)
            print(f"Position: {leg_target_price}")
        elif side == "BUY":
            leg_target_price = closest_current_price + (creds.strike_interval * creds.ATM_CALL_BUY)
            print(f"Position: {leg_target_price}")

        hedge_target_price = closest_current_price + (creds.strike_interval * creds.OTM_CALL_HEDGE)

        await self.dprint(f"Leg: {leg_target_price} Hedge: {leg_target_price}")

        if creds.close_hedges and side.upper() == "SELL" and creds.active_close_hedges:
            call_hedge_contract, self.otm_call_fill, self.otm_call_id = await self.place_order(side="BUY", type="C",
                                                                                               strike=hedge_target_price,
                                                                                               quantity=creds.call_hedge_quantity)
            while self.should_continue:
                open_orders = await self.broker.get_open_orders()
                matching_order = next((trade for trade in open_orders if trade.order.orderId == self.otm_call_id), None)

                if matching_order:
                    self.otm_call_fill = matching_order.orderStatus.filled
                    if self.otm_call_fill > 0:
                        print(f"Call hedge {self.otm_call_fill} is filled.")
                    else:
                        print("Call hedge still open but not filled")
                else:
                    print(f"Call hedge {self.otm_call_fill} is no longer in open orders — might be cancelled or filled.")

                await asyncio.sleep(1)

            if self.otm_call_fill > 0:
                self.otm_call_id = None
            elif self.otm_call_fill == 0 and not self.should_continue:
                return

            await self.dprint("Call Hedge Placed")

        quantity = creds.sell_call_position_quantity if side == "SELL" else creds.buy_call_position_quantity
        self.call_contract, self.atm_call_fill, self.atm_call_id = await self.place_order(side=side.upper(), type="C",
                                                                                          strike=leg_target_price,
                                                                                          quantity=quantity)
        print("Call ATM placed")
        while self.should_continue:
            open_orders = await self.broker.get_open_orders()
            matching_order = next((trade for trade in open_orders if trade.order.orderId == self.atm_call_id), None)

            if matching_order:
                self.atm_call_fill = matching_order.orderStatus.filled
                if self.atm_call_fill > 0:
                    print(f"Call Position {self.atm_call_id} is filled.")
                else:
                    print("Call Position still open but not filled")
            else:
                print(f"Call Position {self.atm_call_id} is no longer in open orders — might be cancelled or filled.")

            await asyncio.sleep(1)

        if self.atm_call_fill > 0:
            self.atm_call_id = None
        elif self.atm_call_fill == 0 and not self.should_continue:
            return

        if side.upper() == "SELL":
            self.atm_call_sl = round(self.atm_call_fill * (1 + (creds.call_sl_sell / 100)), 1)
        elif side.upper() == "BUY":
            self.atm_call_sl = round(self.atm_call_fill * (1 - (creds.call_sl_buy / 100)), 1)

        await self.dprint(f"Call Order sl is {self.atm_call_sl}")

        temp_percentage = 1
        while self.atm_call_fill > 0:
            premium_price = await self.broker.get_latest_premium_price(
                symbol=creds.instrument,
                expiry=creds.date,
                strike=leg_target_price,
                right="C"
            )

            if ((premium_price['ask'] >= self.atm_call_sl and side == "SELL") or (premium_price["bid"] <=
                                                                                  self.atm_call_sl
                                                                                  and side == "BUY")):
                pos = creds.buy_call_position_quantity if self.curr_CE_side == "BUY" else (
                    creds.sell_call_position_quantity)

                await self.dprint(
                    f"[CALL] Stop loss triggered"
                    f"\nCurrent Premium: {premium_price}"
                    f"\nStop Loss Level: {self.atm_call_sl}"
                    f"\nStrike Price: {leg_target_price}"
                    f"\nPosition Size: {pos}"
                )
                stp_side = "BUY" if side == "SELL" else "SELL"
                await self.broker.place_market_order(contract=self.call_contract, qty=pos,
                                                     side=stp_side)
                if creds.close_hedges and side == "SELL":
                    await self.place_order(side="SELL", type="C", strike=hedge_target_price,
                                           quantity=creds.call_hedge_quantity)
                return

            if ((premium_price['ask'] <= self.atm_call_fill - temp_percentage * (
                    creds.sell_call_entry_price_changes_by / 100) * self.atm_call_fill and side == "SELL") or
                    (premium_price['bid'] >= self.atm_call_fill + temp_percentage * (
                            creds.buy_call_entry_price_changes_by / 100) * self.atm_call_fill and side == "BUY")):

                if side == "SELL":
                    self.atm_call_sl = self.atm_call_sl - (self.atm_call_fill * (creds.sell_call_change_sl_by / 100))
                    self.atm_call_sl = round(self.atm_call_sl, 1)
                elif side == "BUY":
                    self.atm_call_sl = self.atm_call_sl + (self.atm_call_fill * (creds.buy_call_change_sl_by / 100))
                    self.atm_call_sl = round(self.atm_call_sl, 1)

                await self.dprint(
                    f"[CALL] Price dip detected - Adjusting trailing parameters"
                    f"\nFill Price: {self.atm_call_fill}"
                    f"\nCurrent Premium: {premium_price}"
                    f"\nNew SL: {self.atm_call_sl}"
                    f"\nTemp value: {temp_percentage}"
                )

                temp_percentage += 1
                continue

            if not self.should_continue:
                pos = creds.buy_call_position_quantity if self.curr_CE_side == "BUY" else (
                    creds.sell_call_position_quantity)

                await self.dprint("Exiting Call Side")
                stp_side = "BUY" if side == "SELL" else "SELL"
                await self.broker.place_market_order(contract=self.call_contract, qty=pos,
                                                     side=stp_side)
                if creds.close_hedges and side == "SELL":
                    await self.place_order(side="SELL", type="C", strike=hedge_target_price,
                                           quantity=creds.call_hedge_quantity)
                return

            await asyncio.sleep(1)

    async def place_put_order(self, side: str):
        current_price = await self.get_current_price()
        closest_current_price = await self.get_closest_price(current_price)
        leg_target_price = 0
        if side == "SELL":
            leg_target_price = closest_current_price - (creds.strike_interval * creds.ATM_PUT_SELL)
            print(f"Position: {leg_target_price}")
        elif side == "BUY":
            leg_target_price = closest_current_price - (creds.strike_interval * creds.ATM_PUT_BUY)
            print(f"Position: {leg_target_price}")
        hedge_target_price = closest_current_price - (creds.strike_interval * creds.OTM_PUT_HEDGE)

        await self.dprint(f"Leg: {leg_target_price} Hedge: {leg_target_price}")

        if creds.close_hedges and side.upper() == "SELL" and creds.active_close_hedges:
            put_hedge_contract, self.otm_put_fill, self.otm_put_id = await self.place_order(side="BUY", type="P",
                                                                                           strike=hedge_target_price,
                                                                                           quantity=creds.put_hedge_quantity)
            while self.should_continue:
                open_orders = await self.broker.get_open_orders()
                matching_order = next((trade for trade in open_orders if trade.order.orderId == self.otm_put_id), None)

                if matching_order:
                    self.otm_put_fill = matching_order.orderStatus.filled
                    if self.otm_put_fill > 0:
                        print(f"Put Hedge {self.otm_put_fill} is filled.")
                    else:
                        print("Put Hedge still open but not filled")
                else:
                    print(f"Put Hedge {self.otm_put_fill} is no longer in open orders — might be cancelled or filled.")

                await asyncio.sleep(1)

            if self.otm_put_fill > 0:
                self.otm_put_id = None
            elif self.otm_put_fill == 0 and not self.should_continue:
                return

            await self.dprint("Put Hedge Placed")

        quantity = creds.sell_put_position_quantity if side == "SELL" else creds.buy_put_position_quantity
        self.put_contract, self.atm_put_fill, self.atm_put_id = await self.place_order(side=side.upper(), type="P",
                                                                                       strike=leg_target_price,
                                                                                       quantity=quantity)
        print("Put ATM placed")
        while self.should_continue:
            open_orders = await self.broker.get_open_orders()
            matching_order = next((trade for trade in open_orders if trade.order.orderId == self.atm_put_id), None)

            if matching_order:
                self.atm_put_fill = matching_order.orderStatus.filled
                if self.atm_put_fill > 0:
                    print(f"Put Position {self.atm_put_fill} is filled.")
                else:
                    print("Put Position still open but not filled")
            else:
                print(f"Put Position {self.atm_put_fill} is no longer in open orders — might be cancelled or filled.")

            await asyncio.sleep(1)

        if self.atm_put_fill > 0:
            self.atm_put_id = None
        elif self.atm_put_fill == 0 and not self.should_continue:
            return

        if side.upper() == "SELL":
            self.atm_put_sl = round(self.atm_put_fill * (1 + (creds.put_sl_sell / 100)), 1)
        elif side.upper() == "BUY":
            self.atm_put_sl = round(self.atm_put_fill * (1 - (creds.put_sl_buy / 100)), 1)

        await self.dprint(f"Put Order sl is {self.atm_put_sl}")

        temp_percentage = 1
        while self.atm_put_fill:
            premium_price = await self.broker.get_latest_premium_price(
                symbol=creds.instrument,
                expiry=creds.date,
                strike=leg_target_price,
                right="P"
            )

            if ((premium_price['bid'] >= self.atm_put_sl and side == "SELL") or (premium_price["ask"] <=
                                                                                 self.atm_put_sl
                                                                                 and side == "BUY")):
                pos = creds.buy_put_position_quantity if self.curr_PE_side == "BUY" else (
                    creds.sell_put_position_quantity)
                await self.dprint(
                    f"[PUT] Stop loss triggered"
                    f"\nCurrent Premium: {premium_price}"
                    f"\nStop Loss Level: {self.atm_put_sl}"
                    f"\nStrike Price: {leg_target_price}"
                    f"\nPosition Size: {pos}"
                )
                stp_side = "BUY" if side == "SELL" else "SELL"
                await self.broker.place_market_order(contract=self.put_contract, qty=pos,
                                                     side=stp_side)
                if creds.close_hedges and side == "SELL":
                    await self.place_order(side="SELL", type="P", strike=hedge_target_price,
                                           quantity=creds.put_hedge_quantity)
                return

            if ((premium_price['ask'] <= self.atm_put_fill - temp_percentage * (
                    creds.sell_put_entry_price_changes_by / 100) * self.atm_put_fill and side == "SELL") or
                    (premium_price['bid'] >= self.atm_put_fill + temp_percentage * (
                            creds.buy_put_entry_price_changes_by / 100) * self.atm_put_fill and side == "BUY")):

                if side == "SELL":
                    self.atm_put_sl = self.atm_put_sl - (self.atm_put_fill * (creds.sell_put_change_sl_by / 100))
                    self.atm_put_sl = round(self.atm_put_sl, 1)
                elif side == "BUY":
                    self.atm_put_sl = self.atm_put_sl + (self.atm_put_fill * (creds.buy_put_change_sl_by / 100))
                    self.atm_put_sl = round(self.atm_put_sl, 1)

                await self.dprint(
                    f"[PUT] Price dip detected - Adjusting trailing parameters"
                    f"\nFill Price: {self.atm_put_fill}"
                    f"\nCurrent Premium: {premium_price}"
                    f"\nNew SL: {self.atm_put_sl}"
                    f"\nTemp value: {temp_percentage}"
                )

                temp_percentage += 1
                continue

            if not self.should_continue:
                pos = creds.buy_put_position_quantity if self.curr_PE_side == "BUY" else (
                    creds.sell_put_position_quantity)
                await self.dprint("Exiting Put Side")
                stp_side = "BUY" if side == "SELL" else "SELL"
                await self.broker.place_market_order(contract=self.put_contract, qty=pos,
                                                     side=stp_side)
                if creds.close_hedges and side == "SELL":
                    await self.place_order(side="SELL", type="P", strike=hedge_target_price,
                                           quantity=creds.put_hedge_quantity)
                return

            await asyncio.sleep(1)

    async def call_side_handler(self):
        while self.should_continue:
            if self.curr_CE_side == "SELL":
                if self.CE_BUY_REENTRY < creds.CE_BUY_REENTRY:
                    self.curr_CE_side = "BUY"
                    await self.place_call_order("BUY")
                    self.CE_BUY_REENTRY += 1
                    await self.dprint("CALL BUY SIDE CLOSED")
                else:
                    await self.dprint("CALL SIDE BUY RE-ENTRY LIMIT REACHED")
                    return
            elif self.curr_CE_side == "BUY":
                if self.CE_SELL_REENTRY < creds.CE_SELL_REENTRY:
                    self.curr_CE_side = "SELL"
                    await self.place_call_order("SELL")
                    self.CE_SELL_REENTRY += 1
                    await self.dprint("CALL SELL SIDE CLOSED")
                else:
                    await self.dprint("CALL SIDE SELL RE-ENTRY LIMIT REACHED")
            await asyncio.sleep(0.5)

    async def put_side_handler(self):
        while self.should_continue:
            if self.curr_PE_side == "SELL":
                if self.PE_BUY_REENTRY < creds.PE_BUY_REENTRY:
                    self.curr_PE_side = "BUY"
                    await self.place_put_order("BUY")
                    self.PE_BUY_REENTRY += 1
                    await self.dprint("PUT BUY SIDE CLOSED")
                else:
                    await self.dprint("PUT SIDE BUY RE-ENTRY LIMIT REACHED")
                    return
            elif self.curr_PE_side == "BUY":
                if self.PE_SELL_REENTRY < creds.PE_SELL_REENTRY:
                    self.curr_PE_side = "SELL"
                    await self.place_put_order("SELL")
                    self.PE_SELL_REENTRY += 1
                    await self.dprint("PUT SELL SIDE CLOSED")
                else:
                    await self.dprint("PUT SIDE BUY RE-ENTRY LIMIT REACHED")
            await asyncio.sleep(0.5)

    async def close_all_positions(self):
        if self.testing:
            return
        else:
            while True:
                current_time = datetime.now(timezone('Europe/Paris'))
                target_time = current_time.replace(
                    hour=creds.exit_hour,
                    minute=creds.exit_minute,
                    second=creds.exit_second,
                    microsecond=0)

                if current_time >= target_time:
                    self.should_continue = False

                    if self.atm_call_id is not None:
                        await self.broker.cancel_order(self.atm_call_id)
                    if self.atm_put_id is not None:
                        await self.broker.cancel_order(self.atm_put_id)
                    if self.otm_call_id is not None:
                        await self.broker.cancel_order(self.otm_call_id)
                    if self.otm_put_id is not None:
                        await self.broker.cancel_order(self.otm_put_id)

                    break

                await asyncio.sleep(10)

    async def open_hedges(self):
        current_price = await self.get_current_price()
        closest_current_price = await self.get_closest_price(current_price)
        hedge_call_target_price = closest_current_price + (creds.strike_interval * creds.OTM_CALL_HEDGE)
        hedge_put_target_price = closest_current_price - (creds.strike_interval * creds.OTM_CALL_HEDGE)
        await asyncio.gather(
            self.place_order(side="BUY", type="C", strike=hedge_call_target_price, quantity=creds.call_hedge_quantity),
            self.place_order(side="BUY", type="P", strike=hedge_put_target_price, quantity=creds.put_hedge_quantity)
        )

    async def main(self):
        await send_discord_message("." * 100)
        await self.dprint("\n1. Testing connection...")
        await self.broker.connect()
        await self.dprint(f"Connection status: {self.broker.is_connected()}")
        self.strikes = await self.broker.fetch_strikes(creds.instrument, "EUREX",
                                                       secType="IND")
        if self.reset:
            # await self.close_all_positions(test=True)
            return

        if self.func_test:
            x, y, z = await self.place_order("BUY", "C", 5350, 1)
            if y != 0:
                z = None
            while self.should_continue:
                open_orders = await self.broker.get_open_orders()
                matching_order = next((trade for trade in open_orders if trade.order.orderId == z), None)

                if matching_order:
                    y = matching_order.orderStatus.filled
                    if y > 0:
                        print(f"Order {z} is filled.")
                        return
                    else:
                        print("Order still open but not filled")
                else:
                    print(f"Order {z} is no longer in open orders — might be cancelled or filled.")
                    return

                await asyncio.sleep(1)

            return

        if creds.active_close_hedges:
            if not creds.close_hedges:
                await self.open_hedges()
                await self.dprint("Hedges will only be placed once in the beginning")
            else:
                await self.dprint("Hedges will close and open with the sell side")
                pass
        else:
            await self.dprint("Hedges Disabled")

        while True:
            current_time = datetime.now(timezone('Europe/Paris'))
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
                await asyncio.gather(
                    self.call_side_handler(),
                    self.put_side_handler(),
                    self.close_all_positions(),
                )
            else:
                await self.dprint("Market is currently closed")
                await asyncio.sleep(30)

                if not self.should_continue:
                    exit()


if __name__ == "__main__":
    s = Strategy()
    asyncio.run(s.main())
