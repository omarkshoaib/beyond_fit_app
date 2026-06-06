"""Product: a single balanced diet style — no vegan/keto/vegetarian/pescatarian options."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot import _dn_ask_diet_style


@pytest.mark.asyncio
async def test_diet_picker_offers_only_balanced():
    msg_or_query = MagicMock()
    msg_or_query.message.reply_text = AsyncMock()
    ctx = MagicMock()

    await _dn_ask_diet_style(msg_or_query, ctx, edit=False)

    _, kwargs = msg_or_query.message.reply_text.call_args
    markup = kwargs["reply_markup"]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]

    assert callbacks == ["dn_diet_balanced"], f"expected only balanced, got {callbacks}"
    for banned in ("dn_diet_vegan", "dn_diet_keto", "dn_diet_vegetarian", "dn_diet_pescatarian"):
        assert banned not in callbacks
