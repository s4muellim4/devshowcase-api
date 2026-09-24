import os
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

# Ajuste de compatibilidade para o SQLAlchemy usar o psycopg 3 com Supabase/Render
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    technology: Mapped[str] = mapped_column(nullable=False, index=True)
    upvotes: Mapped[int] = mapped_column(default=0)
    nota_media: Mapped[float] = mapped_column(default=0.0)

    feedbacks: Mapped[List["FeedbackModel"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class FeedbackModel(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rating: Mapped[int] = mapped_column(nullable=False)
    comment: Mapped[str] = mapped_column(nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    project: Mapped["ProjectModel"] = relationship(back_populates="feedbacks")


Base.metadata.create_all(bind=engine)


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Nota de 1 a 5")
    comment: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="Comentário sobre o projeto",
    )


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rating: int
    comment: str


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    technology: str
    upvotes: int
    nota_media: float
    feedbacks: List[FeedbackResponse] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=150)
    description: str = Field(..., min_length=10, max_length=2000)
    technology: str = Field(..., min_length=2, max_length=100)


app = FastAPI(
    title="DevShowcase API",
    description="API para cadastro, feedbacks, upvotes e busca de projetos de desenvolvedores.",
    version="1.0.0",
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": exc.status_code,
            "error": "Recurso Não Encontrado" if exc.status_code == 404 else "Erro na Requisição",
            "message": exc.detail,
            "path": request.url.path,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error["loc"])
        errors.append(f"Campo '{field}': {error['msg']}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": 400,
            "error": "Bad Request",
            "message": "Dados de entrada inválidos.",
            "details": errors,
            "path": request.url.path,
        },
    )


@app.post("/api/projects", response_model=ProjectResponse, status_code=201, tags=["Projetos"])
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    db_project = ProjectModel(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@app.get("/api/projects", response_model=List[ProjectResponse], tags=["Projetos"])
def list_projects(
    technology: Optional[str] = Query(None, description="Filtrar projetos por tecnologia"),
    page: int = Query(0, ge=0, description="Número da página"),
    size: int = Query(10, ge=1, le=50, description="Quantidade por página"),
    db: Session = Depends(get_db),
):
    query = db.query(ProjectModel)

    if technology:
        query = query.filter(ProjectModel.technology.ilike(f"%{technology}%"))

    return query.offset(page * size).limit(size).all()


@app.put("/api/projects/{id}/upvote", response_model=ProjectResponse, tags=["Projetos"])
def upvote_project(id: int, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Projeto com ID {id} não foi encontrado.")

    project.upvotes += 1
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/projects/{id}/feedbacks", response_model=ProjectResponse, status_code=201, tags=["Feedbacks"])
def add_feedback(id: int, feedback_in: FeedbackCreate, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Projeto com ID {id} não foi encontrado.")

    new_feedback = FeedbackModel(
        rating=feedback_in.rating,
        comment=feedback_in.comment,
        project_id=id,
    )
    db.add(new_feedback)
    db.commit()

    feedbacks = db.query(FeedbackModel).filter(FeedbackModel.project_id == id).all()
    total_rating = sum(f.rating for f in feedbacks)
    project.nota_media = round(total_rating / len(feedbacks), 2)

    db.commit()
    db.refresh(project)
    return project 
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, Depends, Query, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELOS DO BANCO DE DADOS (SQLAlchemy) ---
class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    technology = Column(String, nullable=False, index=True)
    upvotes = Column(Integer, default=0)
    nota_media = Column(Float, default=0.0)

    feedbacks = relationship("FeedbackModel", back_populates="project", cascade="all, delete-orphan")


class FeedbackModel(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    project = relationship("ProjectModel", back_populates="feedbacks")

Base.metadata.create_all(bind=engine)

# --- SCHEMAS DE VALIDAÇÃO (Pydantic) ---
class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Nota de 1 a 5")
    comment: str = Field(..., min_length=2, description="Comentário sobre o projeto")

class FeedbackResponse(BaseModel):
    id: int
    rating: int
    comment: str

    class Config:
        from_attributes = True

class ProjectResponse(BaseModel):
    id: int
    title: str
    description: str
    technology: str
    upvotes: int
    nota_media: float
    feedbacks: List[FeedbackResponse] = []

    class Config:
        from_attributes = True

class ProjectCreate(BaseModel):
    title: str
    description: str
    technology: str

# --- APLICAÇÃO FASTAPI ---
app = FastAPI(
    title="DevShowcase API",
    description="API para cadastro, feedbacks, upvotes e busca de projetos de desenvolvedores.",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- TRATAMENTO GLOBAL DE EXCEÇÕES ---
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": exc.status_code,
            "error": "Recurso Não Encontrado" if exc.status_code == 404 else "Erro na Requisição",
            "message": exc.detail,
            "path": request.url.path
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        field = " -> ".join([str(loc) for loc in error["loc"]])
        errors.append(f"Campo '{field}': {error['msg']}")
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": 400,
            "error": "Bad Request",
            "message": "Dados de entrada inválidos.",
            "details": errors,
            "path": request.url.path
        }
    )

# --- ENDPOINTS / ROTAS DA API ---

@app.post("/api/projects", response_model=ProjectResponse, status_code=201, tags=["Projetos"])
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    db_project = ProjectModel(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

@app.get("/api/projects", response_model=List[ProjectResponse], tags=["Projetos"])
def list_projects(
    technology: Optional[str] = Query(None, description="Filtrar projetos por tecnologia"),
    page: int = Query(0, ge=0, description="Número da página"),
    size: int = Query(10, ge=1, le=50, description="Quantidade por página"),
    db: Session = Depends(get_db)
):
    query = db.query(ProjectModel)
    if technology:
        query = query.filter(ProjectModel.technology.ilike(f"%{technology}%"))
    offset = page * size
    return query.offset(offset).limit(size).all()

@app.put("/api/projects/{id}/upvote", response_model=ProjectResponse, tags=["Projetos"])
def upvote_project(id: int, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Projeto com ID {id} não foi encontrado.")
    project.upvotes += 1
    db.commit()
    db.refresh(project)
    return project

@app.post("/api/projects/{id}/feedbacks", response_model=ProjectResponse, status_code=201, tags=["Feedbacks"])
def add_feedback(id: int, feedback_in: FeedbackCreate, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Projeto com ID {id} não foi encontrado.")
    
    new_feedback = FeedbackModel(
        rating=feedback_in.rating,
        comment=feedback_in.comment,
        project_id=id
    )
    db.add(new_feedback)
    db.commit()
    
    feedbacks = db.query(FeedbackModel).filter(FeedbackModel.project_id == id).all()
    total_rating = sum(f.rating for f in feedbacks)
    project.nota_media = round(total_rating / len(feedbacks), 2)
    
    db.commit()
    db.refresh(project)
    return project