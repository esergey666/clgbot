import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from bot.receipts import handlers as h
from bot.services.access import AccessService


class ReceiptDialogTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = SimpleNamespace(access_users_path=Path(self.temp.name) / 'users.json', admin_ids=[123])
        self.access = AccessService(self.config.access_users_path)
        self.access.add_balance(123, 1000)
        self.state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=123, user_id=123))
        self.message = SimpleNamespace(answer=AsyncMock(), answer_document=AsyncMock(), text=None,
                                       from_user=SimpleNamespace(id=123))
        self.callback = SimpleNamespace(answer=AsyncMock(), message=self.message, from_user=SimpleNamespace(id=123))

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def fill(self):
        await h.begin(self.message, self.state, 123, self.config)
        await h.accept_date(self.message, self.state, '23.09.2026')
        for value in ('2', 'FELPA CON CAPPUCCIO', 'L', 'V0029', '811564151', '255,00', '170,50'):
            self.message.text = value
            await h.input_item(self.message, self.state)
        await h.finish(self.callback, self.state)

    async def test_admin_dialog_preserves_preview_without_charge(self):
        await self.fill()
        data = await self.state.get_data()
        self.assertEqual(data['fr_receipt']['total_ttc'], '341.00')
        self.assertEqual(data['fr_receipt']['items'][0]['name_it'], 'FELPA CON CAPPUCCIO')
        self.assertEqual(await self.state.get_state(), h.ReceiptForm.confirm.state)
        with patch.object(h, 'render', return_value=b'png') as render:
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(render.call_args.args[0].to_dict(), data['fr_receipt'])
        self.assertEqual(self.access.get_balance(123), 1000)
        self.assertEqual(self.message.answer_document.await_count, 3)
        self.assertTrue(self.message.answer_document.call_args.args[0].filename.endswith('.png'))
        self.assertIsNone(await self.state.get_state())

    async def test_admin_failed_delivery_retry_does_not_charge(self):
        await self.fill()
        self.message.answer_document.side_effect = [RuntimeError('network'), None, None, None]
        with patch.object(h, 'render', return_value=b'png'), patch.object(h.logger, 'exception'):
            await h.create(self.callback, self.state, self.config)
            self.assertEqual(self.access.get_balance(123), 1000)
            self.assertTrue((await self.state.get_data())['fr_paid'])
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(self.access.get_balance(123), 1000)
        self.assertIsNone(await self.state.get_state())

    async def test_tag_failure_resumes_without_resending_receipt(self):
        await self.fill()
        self.message.answer_document.side_effect = [None, RuntimeError('tag network'), None, None]
        with patch.object(h, 'render', return_value=b'png'), patch.object(h.logger, 'exception'):
            await h.create(self.callback, self.state, self.config)
            data = await self.state.get_data()
            self.assertTrue(data['fr_png_sent'])
            self.assertEqual(data['fr_tags_sent'], 0)
            await h.create(self.callback, self.state, self.config)
        filenames = [call.args[0].filename for call in self.message.answer_document.call_args_list]
        self.assertEqual(sum(name.startswith('receipt_') for name in filenames), 1)
        self.assertEqual(filenames[1], filenames[2])
        self.assertEqual(self.access.get_balance(123), 1000)

    async def test_base_sticker_failure_resumes_without_resending_other_files(self):
        await self.fill()
        self.message.answer_document.side_effect = [None, None, RuntimeError('network'), None]
        with patch.object(h, 'render', return_value=b'png'), patch.object(h.logger, 'exception'):
            await h.create(self.callback, self.state, self.config)
            data = await self.state.get_data()
            self.assertTrue(data['fr_png_sent'])
            self.assertEqual(data['fr_tags_sent'], 1)
            self.assertEqual(data['fr_stickers_sent'], 0)
            await h.create(self.callback, self.state, self.config)
        filenames = [call.args[0].filename for call in self.message.answer_document.call_args_list]
        self.assertEqual(filenames[2], filenames[3])
        self.assertEqual(self.access.get_balance(123), 1000)
        self.assertIsNone(await self.state.get_state())

    async def test_multiple_positions_send_one_receipt_and_each_tag(self):
        await self.fill()
        data = await self.state.get_data()
        from bot.receipts.models import Receipt, ReceiptItem
        from bot.receipts.config import StoreConfig
        from datetime import date
        items = [ReceiptItem.from_dict({key: value for key, value in data['fr_items'][0].items()
                                       if key != 'product_barcode'}) for _ in range(5)]
        receipt = Receipt.create(date(2026, 9, 23), items, StoreConfig())
        await self.state.update_data(fr_receipt=receipt.to_dict())
        with patch.object(h, 'render', return_value=b'png'):
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(self.message.answer_document.await_count, 11)
        self.assertEqual(self.access.get_balance(123), 1000)

    async def test_render_failure_does_not_charge(self):
        await self.fill()
        with patch.object(h, 'render', side_effect=ValueError('bad')), patch.object(h.logger, 'exception'):
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(self.access.get_balance(123), 1000)
        self.message.answer_document.assert_not_awaited()

    async def test_invalid_input_stays_on_same_step(self):
        await h.begin(self.message, self.state, 123, self.config)
        await h.accept_date(self.message, self.state, '-')
        self.message.text = '0'
        await h.input_item(self.message, self.state)
        self.assertEqual((await self.state.get_data())['fr_step'], 0)

    async def test_20_item_limit(self):
        await self.fill()
        data = await self.state.get_data()
        await self.state.update_data(fr_items=data['fr_items'] * 20)
        await self.state.set_state(h.ReceiptForm.more)
        await h.next_item(self.message, self.state)
        self.assertEqual(await self.state.get_state(), h.ReceiptForm.more.state)
        self.assertEqual(len((await self.state.get_data())['fr_items']), 20)

    async def test_non_admin_cannot_start_even_with_balance(self):
        self.config.admin_ids = []
        await h.command_start(self.message, self.state, self.config)
        self.assertIsNone(await self.state.get_state())
        self.message.answer.assert_awaited_once_with(h.UNAVAILABLE)
        self.assertEqual(self.access.get_balance(123), 1000)

    async def test_revoked_admin_cannot_generate_even_paid_preview(self):
        for paid in (False, True):
            self.config.admin_ids = [123]
            await self.fill()
            await self.state.update_data(fr_paid=paid)
            self.config.admin_ids = []
            with patch.object(h, 'render') as render, patch.object(h, 'render_price_tags') as tags, patch.object(h, 'render_base_stickers') as stickers:
                await h.create(self.callback, self.state, self.config)
                render.assert_not_called()
                tags.assert_not_called()
                stickers.assert_not_called()
            self.callback.answer.assert_awaited_with(h.UNAVAILABLE, show_alert=True)
            self.message.answer_document.assert_not_awaited()
            self.assertIsNone(await self.state.get_state())
            self.assertEqual(self.access.get_balance(123), 1000)

    async def test_middleware_blocks_existing_wizard_and_stale_callbacks(self):
        from unittest.mock import MagicMock
        from aiogram.types import CallbackQuery, Message
        guard = h.AdminOnlyReceiptMiddleware()
        self.config.admin_ids = []
        for event_type in (Message, CallbackQuery):
            for current in h.ReceiptForm.__all_states_names__:
                event = MagicMock(spec=event_type)
                event.from_user = SimpleNamespace(id=123)
                event.answer = AsyncMock()
                handler = AsyncMock()
                await self.state.set_state(current)
                await guard(handler, event, {'config': self.config, 'state': self.state})
                handler.assert_not_awaited()
                self.assertIsNone(await self.state.get_state())
                self.assertEqual(event.answer.call_args.args[0], h.UNAVAILABLE)
        await self.state.set_state('OtherForm:input')
        await guard(handler, event, {'config': self.config, 'state': self.state})
        self.assertEqual(await self.state.get_state(), 'OtherForm:input')

    async def test_middleware_passes_admin(self):
        handler = AsyncMock(return_value='allowed')
        result = await h.AdminOnlyReceiptMiddleware()(handler, self.message, {'config': self.config, 'state': self.state})
        self.assertEqual(result, 'allowed')
        handler.assert_awaited_once()

    async def test_real_router_enforces_admin_boundary(self):
        from datetime import datetime, timezone
        from aiogram import Bot, Dispatcher
        from aiogram.types import Update, Message, Chat, User, CallbackQuery
        from aiogram.methods import SendMessage, AnswerCallbackQuery
        session = AsyncMock()
        bot = Bot('123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789', session=session)
        dispatcher = Dispatcher(storage=MemoryStorage(), config=self.config)
        dispatcher.include_router(h.router)
        user = User(id=123, is_bot=False, first_name='Test')
        message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=123, type='private'),
                          from_user=user, text='/receipt_fr')
        self.config.admin_ids = []
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))
        sent = session.call_args.args[1]
        self.assertIsInstance(sent, SendMessage)
        self.assertEqual(sent.text, h.UNAVAILABLE)
        state = dispatcher.fsm.get_context(bot=bot, chat_id=123, user_id=123)
        for index, action in enumerate(('start', 'today', 'add', 'finish', 'edit', 'create', 'cancel', 'obsolete'), 2):
            await state.set_state(h.ReceiptForm.confirm)
            await state.update_data(fr_paid=True)
            callback = CallbackQuery(id=str(index), from_user=user, chat_instance='test',
                                     message=message, data='fr:' + action)
            with patch.object(h, 'render') as render:
                await dispatcher.feed_update(bot, Update(update_id=index, callback_query=callback))
                render.assert_not_called()
            sent = session.call_args.args[1]
            self.assertIsInstance(sent, AnswerCallbackQuery)
            self.assertEqual(sent.text, h.UNAVAILABLE)
            self.assertTrue(sent.show_alert)
            self.assertIsNone(await state.get_state())
        # Unrelated messages are not swallowed by receipt-specific middleware.
        session.reset_mock()
        await dispatcher.feed_update(bot, Update(update_id=20, message=message.model_copy(update={'text': 'hello'})))
        session.assert_not_awaited()
        self.config.admin_ids = [123]
        await dispatcher.feed_update(bot, Update(update_id=21, message=message))
        self.assertEqual(await state.get_state(), h.ReceiptForm.date.state)
