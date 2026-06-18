from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from models import UserRole


def get_main_menu_keyboard(role: UserRole) -> ReplyKeyboardMarkup:
    """Главное меню в зависимости от роли"""
    buttons = []

    # Общие кнопки для всех
    buttons.append([KeyboardButton(text="📋 Мои задачи")])
    buttons.append([KeyboardButton(text="📊 Статистика")])

    # Кнопки по ролям
    if role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
        buttons.append([KeyboardButton(text="➕ Создать задачу")])

    if role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
        buttons.append([KeyboardButton(text="📦 Материалы")])

    if role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
        buttons.append([KeyboardButton(text="🔧 Инструменты")])

    if role == UserRole.FOREMAN:
        buttons.append([KeyboardButton(text="📝 Заявка на материалы")])

    if role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]:
        buttons.append([KeyboardButton(text="📈 Отчёты")])

    if role == UserRole.OWNER:
        buttons.append([KeyboardButton(text="👥 Пользователи")])
        buttons.append([KeyboardButton(text="🏗️ Объекты")])

    buttons.append([KeyboardButton(text="🌐 Веб-панель")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_task_actions_keyboard(task_id: int, user_role: UserRole) -> InlineKeyboardMarkup:
    """Действия с задачей"""
    buttons = []

    if user_role in [UserRole.ELECTRICIAN, UserRole.WORKER]:
        buttons.append([InlineKeyboardButton(text="▶️ Начать", callback_data=f"task_start_{task_id}")])
        buttons.append([InlineKeyboardButton(text="📸 Сдать фото", callback_data=f"task_photo_{task_id}")])

    if user_role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
        buttons.append([InlineKeyboardButton(text="✅ Утвердить", callback_data=f"task_approve_{task_id}")])
        buttons.append([InlineKeyboardButton(text="❌ Отклонить", callback_data=f"task_reject_{task_id}")])

    if user_role in [UserRole.GENERAL_DIRECTOR, UserRole.OWNER]:
        buttons.append([InlineKeyboardButton(text="💰 Оплатить", callback_data=f"task_pay_{task_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_objects_keyboard(objects: list) -> InlineKeyboardMarkup:
    """Выбор объекта"""
    buttons = []
    for obj in objects:
        buttons.append([InlineKeyboardButton(text=obj.name, callback_data=f"object_{obj.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_users_keyboard(users: list) -> InlineKeyboardMarkup:
    """Выбор пользователя"""
    buttons = []
    for user in users:
        role_emoji = {
            UserRole.OWNER: "👑",
            UserRole.GENERAL_DIRECTOR: "💼",
            UserRole.PTO: "📐",
            UserRole.FOREMAN: "👷",
            UserRole.ELECTRICIAN: "⚡",
            UserRole.WORKER: "🔨"
        }.get(user.role, "👤")

        buttons.append([
            InlineKeyboardButton(
                text=f"{role_emoji} {user.full_name}",
                callback_data=f"user_{user.telegram_id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_approval_keyboard(task_id: int, action: str) -> InlineKeyboardMarkup:
    """Клавиатура для утверждения/отклонения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"{action}_yes_{task_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"{action}_no_{task_id}")
        ]
    ])


def get_orders_keyboard(orders: list) -> InlineKeyboardMarkup:
    """Список заявок"""
    buttons = []
    for order in orders:
        status_emoji = {
            "pending_pto": "⏳",
            "pending_owner": "🔍",
            "approved": "✅",
            "rejected": "❌"
        }.get(order.status, "📝")

        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} Заявка #{order.id}",
                callback_data=f"order_{order.id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tools_keyboard(tools: list) -> InlineKeyboardMarkup:
    """Список инструментов"""
    buttons = []
    for tool in tools:
        status_emoji = {
            "available": "✅",
            "assigned": "👤",
            "in_repair": "🔧",
            "written_off": "❌"
        }.get(tool.status, "🔧")

        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {tool.name} ({tool.inventory_number})",
                callback_data=f"tool_{tool.id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )