from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, date
import os
import json
from fpdf import FPDF
from sqlalchemy import select
from database import get_db
from models import User

router = Router()

# Папка для хранения журналов инструктажа
INSTRUCTIONS_DIR = "uploads/instructions"
os.makedirs(INSTRUCTIONS_DIR, exist_ok=True)

# Состояния FSM
class SafetyStates(StatesGroup):
    waiting_for_confirm = State()
    waiting_for_scroll = State()

# Текст инструктажа (полный, как требуется по законодательству РФ)
SAFETY_TEXT = """
🔴 ИНСТРУКТАЖ ПО ТЕХНИКЕ БЕЗОПАСНОСТИ
=======================================

📌 ОБЩИЕ ТРЕБОВАНИЯ
--------------------
1. К работе допускаются лица не моложе 18 лет, прошедшие медицинский осмотр.
2. Работник обязан знать и соблюдать правила внутреннего трудового распорядка.
3. Запрещается употребление алкогольных, наркотических и токсических веществ.

⚡ ЭЛЕКТРОМОНТАЖНЫЕ РАБОТЫ
--------------------------
1. Перед началом работ проверить отключение напряжения.
2. Использовать только исправные инструменты с изолированными рукоятками.
3. Запрещается работать под напряжением выше 42 В без средств защиты.
4. Все соединения выполнять только при полном снятии напряжения.

🔌 СЛАБОТОЧНЫЕ РАБОТЫ
----------------------
1. Соблюдать правила работы с низковольтным оборудованием.
2. Не допускать повреждения изоляции кабелей.
3. Запрещается прокладывать слаботочные кабели вместе с силовыми.

💨 ВЕНТИЛЯЦИОННЫЕ РАБОТЫ
------------------------
1. Перед началом работ проверить исправность вентиляционного оборудования.
2. Использовать средства индивидуальной защиты (каски, перчатки, спецобувь).
3. Не допускать попадания посторонних предметов в вентиляционные системы.

🔥 ПОЖАРНАЯ БЕЗОПАСНОСТЬ
------------------------
1. Курить только в специально отведённых местах.
2. Иметь при себе средства пожаротушения (огнетушитель).
3. Знать пути эвакуации при пожаре.
4. При обнаружении пожара немедленно сообщить руководителю.

🚑 ПЕРВАЯ ПОМОЩЬ
----------------
1. При поражении электрическим током — обесточить пострадавшего.
2. При травмах — наложить жгут и вызвать скорую помощь.
3. При пожаре — звонить 112 или 101.

⚠️ ОТВЕТСТВЕННОСТЬ
-------------------
За нарушение требований инструктажа работник несёт ответственность согласно Трудовому кодексу РФ и внутренним распорядительным документам компании.

✅ Я ОЗНАКОМЛЕН И ПОДТВЕРЖДАЮ, ЧТО ВСЁ ПОНЯТНО
================================================
Нажмите кнопку ниже, чтобы подтвердить прохождение инструктажа.
"""

# Клавиатура для подтверждения
def get_safety_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Ознакомлен и подтверждаю, что всё понятно",
            callback_data="safety_confirm"
        )]
    ])


async def check_safety_briefing(user_id: int) -> bool:
    """Проверяет, прошёл ли пользователь инструктаж сегодня"""
    today = date.today().isoformat()
    safety_file = f"{INSTRUCTIONS_DIR}/{today}/{user_id}.json"
    return os.path.exists(safety_file)


async def require_safety_briefing(message: types.Message) -> bool:
    """
    Проверяет инструктаж. Возвращает True если инструктаж пройден или не требуется.
    Возвращает False если инструктаж нужен (отправляет сообщение).
    """
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "Вы не зарегистрированы в системе.\n"
                "Обратитесь к владельцу для получения доступа."
            )
            return False
        
        # Владельцы и гендиректора НЕ проходят инструктаж
        if user.role in ["owner", "general_director"]:
            return True
        
        # Для остальных проверяем, проходил ли сегодня
        if await check_safety_briefing(message.from_user.id):
            return True
        
        # Не проходил — показываем инструктаж
        await message.answer(
            f"🔴 ВНИМАНИЕ: ОБЯЗАТЕЛЬНЫЙ ИНСТРУКТАЖ ПО ТБ\n\n"
            f"Уважаемый {user.full_name}!\n\n"
            "Перед началом рабочего дня вы должны пройти инструктаж "
            "по технике безопасности.\n\n"
            "Нажмите кнопку 'Пройти инструктаж':",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🛡️ Пройти инструктаж",
                    callback_data="safety_start"
                )]
            ])
        )
        return False


@router.callback_query(lambda c: c.data == "safety_start")
async def safety_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📋 ИНСТРУКЦИЯ ПО ТЕХНИКЕ БЕЗОПАСНОСТИ\n\n"
        "Прочитайте полностью и прокрутите до конца:\n\n"
        f"{SAFETY_TEXT}\n\n"
        "После прочтения нажмите кнопку подтверждения:",
        reply_markup=get_safety_keyboard()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "safety_confirm")
async def safety_confirm(callback: types.CallbackQuery, state: FSMContext):
    today = date.today().isoformat()
    user_id = callback.from_user.id
    
    # Создаём папку для сегодняшней даты
    day_dir = f"{INSTRUCTIONS_DIR}/{today}"
    os.makedirs(day_dir, exist_ok=True)
    
    # Сохраняем факт прохождения инструктажа
    safety_data = {
        "user_id": user_id,
        "username": callback.from_user.username or "unknown",
        "full_name": callback.from_user.full_name or "unknown",
        "timestamp": datetime.now().isoformat(),
        "date": today
    }
    
    with open(f"{day_dir}/{user_id}.json", "w", encoding="utf-8") as f:
        json.dump(safety_data, f, ensure_ascii=False, indent=2)
    
    await callback.message.edit_text(
        "✅ ИНСТРУКТАЖ ПРОЙДЕН УСПЕШНО!\n\n"
        f"📅 Дата: {today}\n"
        f"👤 Работник: {callback.from_user.full_name}\n\n"
        "Теперь вам доступен полный функционал бота.\n"
        "Отправьте /start для продолжения работы."
    )
    await callback.answer()


# Функция генерации ежедневного отчёта (вызывается в 10:00)
async def generate_daily_safety_report():
    today = date.today().isoformat()
    day_dir = f"{INSTRUCTIONS_DIR}/{today}"
    
    if not os.path.exists(day_dir):
        return None
    
    # Собираем данные о прошедших инструктаж
    passed = []
    for file in os.listdir(day_dir):
        if file.endswith(".json"):
            with open(f"{day_dir}/{file}", "r", encoding="utf-8") as f:
                data = json.load(f)
                passed.append(data)
    
    # Получаем всех работников из БД
    async for session in get_db():
        workers = await session.execute(
            select(User).where(User.role.in_(["worker", "electrician", "foreman"]))
        )
        workers = workers.scalars().all()
        
        # Формируем отчёт
        report = f"""
📋 ОТЧЁТ ПО ИНСТРУКТАЖУ ТБ
================================
📅 Дата: {today}
⏰ Время: {datetime.now().strftime('%H:%M')}

✅ ПРОШЛИ ИНСТРУКТАЖ ({len(passed)} чел.):
"""
        for p in passed:
            report += f"   • {p.get('full_name', 'Unknown')} — {p.get('timestamp', '')}\n"
        
        # Кто не прошёл
        passed_ids = [p['user_id'] for p in passed]
        not_passed = [w for w in workers if w.telegram_id not in passed_ids]
        
        report += f"\n❌ НЕ ПРОШЛИ ИНСТРУКТАЖ ({len(not_passed)} чел.):\n"
        for w in not_passed:
            report += f"   • {w.full_name} (ID: {w.telegram_id})\n"
    
    # Генерируем PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Отчёт по инструктажу ТБ", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Дата: {today}", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Прошли инструктаж:", ln=True)
    pdf.set_font("Arial", "", 12)
    for p in passed:
        pdf.cell(0, 8, f"• {p.get('full_name', 'Unknown')} — {p.get('timestamp', '')}", ln=True)
    
    pdf.ln(5)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Не прошли инструктаж:", ln=True)
    pdf.set_font("Arial", "", 12)
    for w in not_passed:
        pdf.cell(0, 8, f"• {w.full_name} (ID: {w.telegram_id})", ln=True)
    
    # Сохраняем PDF
    pdf_path = f"{day_dir}/safety_report_{today}.pdf"
    pdf.output(pdf_path)
    
    return pdf_path, report, passed, not_passed
