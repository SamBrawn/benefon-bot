from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from datetime import datetime, timedelta
import uuid
import traceback
from database import get_db
from models import User, Task, WebToken, Material, SalaryLog
from config import settings
from loguru import logger

app = FastAPI(title="Benefon Bot Web Panel")
templates = Jinja2Templates(directory="web/templates")


# Глобальный обработчик ошибок
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Web panel global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Внутренняя ошибка сервера", "detail": str(exc)}
    )


@app.get("/")
async def root():
    """Редирект на логин"""
    try:
        return RedirectResponse(url="/web_login")
    except Exception as e:
        logger.error(f"Root error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/web_login")
async def web_login(request: Request, token: str = None):
    """Страница входа по токену"""
    try:
        if not token:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Токен не указан"})

        async for session in get_db():
            try:
                result = await session.execute(
                    select(WebToken)
                    .where(WebToken.token == uuid.UUID(token))
                    .where(WebToken.expires_at > datetime.utcnow())
                    .where(WebToken.is_used == False)
                )
                web_token = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Token query error: {e}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка проверки токена"})

            if not web_token:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный или истёкший токен"})

            # Получаем пользователя
            try:
                result = await session.execute(
                    select(User).where(User.telegram_id == web_token.user_id)
                )
                user = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"User query error: {e}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка получения пользователя"})

            if not user:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Пользователь не найден"})

            # Отмечаем токен как использованный
            try:
                web_token.is_used = True
                await session.commit()
            except Exception as e:
                logger.error(f"Token update error: {e}")
                # Продолжаем даже если не удалось отметить токен

            return RedirectResponse(url=f"/dashboard?user_id={user.telegram_id}")

    except Exception as e:
        logger.error(f"Web login error: {e}", exc_info=True)
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Внутренняя ошибка"})


@app.get("/dashboard")
async def dashboard(request: Request, user_id: int):
    """Дашборд с графиками"""
    try:
        async for session in get_db():
            try:
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Dashboard user query error: {e}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки пользователя"})

            if not user:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Пользователь не найден"})

            # Статистика
            try:
                result = await session.execute(
                    select(Task.status, func.count(Task.id)).group_by(Task.status)
                )
                task_stats = dict(result.all())

                result = await session.execute(select(func.count(Task.id)))
                total_tasks = result.scalar_one()

                result = await session.execute(select(func.count(Material.id)))
                total_materials = result.scalar_one()

                result = await session.execute(select(func.sum(SalaryLog.amount)))
                total_salary = result.scalar_one() or 0
            except Exception as e:
                logger.error(f"Dashboard stats query error: {e}")
                task_stats = {}
                total_tasks = 0
                total_materials = 0
                total_salary = 0

            return templates.TemplateResponse("dashboard.html", {
                "request": request,
                "user": user,
                "task_stats": task_stats,
                "total_tasks": total_tasks,
                "total_materials": total_materials,
                "total_salary": total_salary
            })

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки дашборда"})


@app.get("/tasks")
async def tasks_page(request: Request, user_id: int, status: str = None):
    """Страница задач"""
    try:
        async for session in get_db():
            try:
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Tasks user query error: {e}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки пользователя"})

            if not user:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Пользователь не найден"})

            try:
                query = select(Task).order_by(Task.created_at.desc())
                if status:
                    query = query.where(Task.status == status)

                result = await session.execute(query)
                tasks = result.scalars().all()
            except Exception as e:
                logger.error(f"Tasks query error: {e}")
                tasks = []

            return templates.TemplateResponse("tasks.html", {
                "request": request,
                "user": user,
                "tasks": tasks,
                "current_status": status
            })

    except Exception as e:
        logger.error(f"Tasks page error: {e}", exc_info=True)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки задач"})


@app.get("/reports")
async def reports_page(request: Request, user_id: int):
    """Страница отчётов"""
    try:
        async for session in get_db():
            try:
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                user = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Reports user query error: {e}")
                return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки пользователя"})

            if not user:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Пользователь не найден"})

            return templates.TemplateResponse("reports.html", {
                "request": request,
                "user": user
            })

    except Exception as e:
        logger.error(f"Reports page error: {e}", exc_info=True)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Ошибка загрузки отчётов"})


@app.get("/logout")
async def logout():
    """Выход"""
    try:
        return RedirectResponse(url="/web_login")
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})