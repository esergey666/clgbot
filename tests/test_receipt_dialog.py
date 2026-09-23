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
        self.config = SimpleNamespace(access_users_path=Path(self.temp.name) / 'users.json', admin_ids=[])
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
        for value in ('2', 'FELPA CON CAPPUCCIO', 'L', 'GRIGIO', '811564151', '255,00', '170,50'):
            self.message.text = value
            await h.input_item(self.message, self.state)
        await h.finish(self.callback, self.state)

    async def test_dialog_preserves_preview_and_charges_once(self):
        await self.fill()
        data = await self.state.get_data()
        self.assertEqual(data['fr_receipt']['total_ttc'], '341.00')
        self.assertEqual(data['fr_receipt']['items'][0]['name_it'], 'FELPA CON CAPPUCCIO')
        self.assertEqual(await self.state.get_state(), h.ReceiptForm.confirm.state)
        with patch.object(h, 'render', return_value=b'png') as render:
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(render.call_args.args[0].to_dict(), data['fr_receipt'])
        self.assertEqual(self.access.get_balance(123), 700)
        self.assertEqual(self.message.answer_document.await_count, 3)
        self.assertTrue(self.message.answer_document.call_args.args[0].filename.endswith('.png'))
        self.assertIsNone(await self.state.get_state())

    async def test_failed_delivery_retry_does_not_charge_again(self):
        await self.fill()
        self.message.answer_document.side_effect = [RuntimeError('network'), None, None, None]
        with patch.object(h, 'render', return_value=b'png'), patch.object(h.logger, 'exception'):
            await h.create(self.callback, self.state, self.config)
            self.assertEqual(self.access.get_balance(123), 700)
            self.assertTrue((await self.state.get_data())['fr_paid'])
            await h.create(self.callback, self.state, self.config)
        self.assertEqual(self.access.get_balance(123), 700)
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
        self.assertEqual(self.access.get_balance(123), 700)

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
        self.assertEqual(self.access.get_balance(123), 700)
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
        self.assertEqual(self.access.get_balance(123), 700)

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
