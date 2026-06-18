from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import uuid
from database import get_db
from models import User, Task, WebToken, Material, SalaryLog
from config import settings

app = FastAPI(title="Benefon Bot Web Panel")
templates = Jinja2Templates(directory="web/templates")


@app.get("/")
async def root():
    """Редирект на логин"""
    return RedirectResponse(url="/web_login")


@app.get("/web_login")
async def web_login(request: Request, token: str = None):
    """Страница входа по токену"""
    if not token:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Токен не указан"})

    async for session in get_db():
        from sqlalchemy import select
        result = await session.execute(
            select(WebToken)
            .where(WebToken.token == uuid.UUID(token))
            .where(WebToken.expires_at > datetime.utcnow())
            .where(WebToken.is_used == False)
        )
        web_token = result.scalar_one_or_none()

        if not web_token:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный или истёкший токен"})

        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == web_token.user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Пользователь не найден"})

        # Отмечаем токен как использованный
        web_token.is_used = True
        await session.commit()

        return RedirectResponse(url=f"/dashboard?user_id={user.telegram_id}")


@app.get("/dashboard")
async def dashboard(request: Request, user_id: int):
    """Дашборд с графиками"""
    async for session in get_db():
        from sqlalchemy import select, func

        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Статистика
        result = await session.execute(
            select(Task.status, func.count(Task.id)).group_by(Task.status)
        )
        task_stats = dict(result.all())

        result = await session.execute(
            select(func.count(Task.id))
        )
        total_tasks = result.scalar_one()

        result = await session.execute(
            select(func.count(Material.id))
        )
        total_materials = result.scalar_one()

        result = await session.execute(
            select(func.sum(SalaryLog.amount))
        )
        total_salary = result.scalar_one() or 0

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": user,
            "task_stats": task_stats,
            "total_tasks": total_tasks,
            "total_materials": total_materials,
            "total_salary": total_salary
        })


@app.get("/tasks")
async def tasks_page(request: Request, user_id: int, status: str = None):
    """Страница задач"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        query = select(Task).order_by(Task.created_at.desc())

        if status:
            query = query.where(Task.status == status)

        result = await session.execute(query)
        tasks = result.scalars().all()

        return templates.TemplateResponse("tasks.html", {
            "request": request,
            "user": user,
            "tasks": tasks,
            "current_status": status
        })


@app.get("/reports")
async def reports_page(request: Request, user_id: int):
    """Страница отчётов"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        return templates.TemplateResponse("reports.html", {
            "request": request,
            "user": user
        })


@app.get("/logout")
async def logout():
    """Выход"""
    return RedirectResponse(url="/web_login")