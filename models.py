from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean,
    DateTime, ForeignKey, Enum, JSON, UUID
)
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from database import Base


class UserRole(str, enum.Enum):
    OWNER = "owner"
    GENERAL_DIRECTOR = "general_director"
    PTO = "pto"
    FOREMAN = "foreman"
    ELECTRICIAN = "electrician"
    WORKER = "worker"


class TaskStatus(str, enum.Enum):
    ASSIGNED = "Назначена"
    IN_PROGRESS = "В работе"
    UNDER_REVIEW = "На проверке"
    APPROVED_BY_FOREMAN = "Утверждена (прорабом)"
    PAID_BY_DIRECTOR = "Оплачена (гендиром)"


class MaterialUnit(str, enum.Enum):
    PIECE = "шт"
    METER = "м"
    SQUARE_METER = "м²"
    LITER = "л"
    KILOGRAM = "кг"
    PACK = "уп"


class ToolStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    IN_REPAIR = "in_repair"
    WRITTEN_OFF = "written_off"


class MaterialOrderStatus(str, enum.Enum):
    PENDING_PTO = "pending_pto"
    PENDING_OWNER = "pending_owner"
    APPROVED = "approved"
    REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    object = relationship("ConstructionObject", back_populates="users")
    assigned_tasks = relationship("Task", foreign_keys="Task.assigned_to", back_populates="assigned_to_user")
    created_tasks = relationship("Task", foreign_keys="Task.assigned_by", back_populates="assigned_by_user")
    salary_logs = relationship("SalaryLog", back_populates="user")
    web_tokens = relationship("WebToken", back_populates="user")


class ConstructionObject(Base):
    __tablename__ = "objects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="object")
    tasks = relationship("Task", back_populates="object")
    materials = relationship("Material", back_populates="object")
    material_orders = relationship("MaterialOrder", back_populates="object")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    work_type = Column(String, nullable=True)
    cost = Column(Float, nullable=True)
    deadline = Column(DateTime, nullable=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.ASSIGNED, nullable=False)
    assigned_to = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    assigned_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=True)
    photos_metadata = Column(JSON, nullable=True)  # [{file_id, file_path, timestamp}]
    location = Column(String, nullable=True)
    approved_by_foreman_at = Column(DateTime, nullable=True)
    paid_by_director_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    object = relationship("ConstructionObject", back_populates="tasks")
    assigned_to_user = relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tasks")
    assigned_by_user = relationship("User", foreign_keys=[assigned_by], back_populates="created_tasks")
    status_history = relationship("TaskStatusHistory", back_populates="task", cascade="all, delete-orphan")
    salary_logs = relationship("SalaryLog", back_populates="task")


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    old_status = Column(Enum(TaskStatus), nullable=True)
    new_status = Column(Enum(TaskStatus), nullable=False)
    changed_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    task = relationship("Task", back_populates="status_history")


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=False)
    name = Column(String, nullable=False)
    unit = Column(Enum(MaterialUnit), nullable=False)
    quantity = Column(Float, nullable=False)
    initial_quantity = Column(Float, nullable=False)
    critical_percent = Column(Float, nullable=True, default=10.0)  # % от начального
    critical_absolute = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    object = relationship("ConstructionObject", back_populates="materials")


class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    inventory_number = Column(String, unique=True, nullable=False, index=True)
    assigned_to = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    status = Column(Enum(ToolStatus), default=ToolStatus.AVAILABLE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    history = relationship("ToolHistory", back_populates="tool", cascade="all, delete-orphan")


class ToolHistory(Base):
    __tablename__ = "tool_history"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)
    from_user = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    to_user = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    date = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tool = relationship("Tool", back_populates="history")


class MaterialOrder(Base):
    __tablename__ = "material_orders"

    id = Column(Integer, primary_key=True, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"), nullable=False)
    materials_json = Column(JSON, nullable=False)  # [{name, quantity, unit}]
    status = Column(Enum(MaterialOrderStatus), default=MaterialOrderStatus.PENDING_PTO, nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    pto_approved_at = Column(DateTime, nullable=True)
    owner_approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    object = relationship("ConstructionObject", back_populates="material_orders")


class SalaryLog(Base):
    __tablename__ = "salary_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="salary_logs")
    task = relationship("Task", back_populates="salary_logs")


class WebToken(Base):
    __tablename__ = "web_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    token = Column(UUID, unique=True, index=True, nullable=False, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)

    # Relationships
    user = relationship("User", back_populates="web_tokens")