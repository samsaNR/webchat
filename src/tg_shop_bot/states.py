from aiogram.fsm.state import State, StatesGroup


class BuyStates(StatesGroup):
    waiting_for_proof = State()


class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()


class AddKeys(StatesGroup):
    waiting_for_keys = State()


class RejectOrder(StatesGroup):
    waiting_for_reason = State()
