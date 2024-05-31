from fastapi import APIRouter, HTTPException, Depends
from databases import Database
from app.dependencies import get_database
from datetime import datetime

from pydantic import BaseModel
from typing import List


class Experience(BaseModel):
    title: str
    company: str
    date: str
    technologies: str
    description: str


class Education(BaseModel):
    degree: str
    institution: str
    date: str


class Course(BaseModel):
    title: str
    provider: str


class CVResponse(BaseModel):
    experiences: List[Experience]
    education: List[Education]
    courses: List[Course]


class Project(BaseModel):
    name: str
    description: str
    link: str


class ProjectsResponse(BaseModel):
    projects: List[Project]

router = APIRouter()


@router.post("/cv")
async def get_cv_text(database: Database = Depends(get_database)):
    async with database.transaction():
        query = "SELECT content, count, last_called FROM cv_text WHERE id = 1 FOR UPDATE"
        result = await database.fetch_one(query)
        if result is None:
            raise HTTPException(status_code=404, detail="CV text not found")

        new_count = result["count"] + 1
        new_last_called = datetime.now()

        update_query = """
            UPDATE cv_text 
            SET count = :new_count, last_called = :new_last_called 
            WHERE id = 1
        """
        await database.execute(update_query, {"new_count": new_count, "new_last_called": new_last_called})

    return {"content": result["content"], "count": new_count, "last_called": new_last_called}


@router.post("/cv_exp", response_model=CVResponse)
async def get_cv_text(database: Database = Depends(get_database)):
    async with database.transaction():
        # Fetch experiences
        experience_query = "SELECT title, company, date, technologies, description FROM cv_experiences"
        experiences = await database.fetch_all(experience_query)

        # Fetch education
        education_query = "SELECT degree, institution, date FROM cv_education"
        education = await database.fetch_all(education_query)

        # Fetch courses
        courses_query = "SELECT title, provider FROM cv_courses"
        courses = await database.fetch_all(courses_query)

    return {
        "experiences": experiences,
        "education": education,
        "courses": courses
    }


@router.post("/cv_projects", response_model=ProjectsResponse)
async def get_projects(database: Database = Depends(get_database)):
    query = "SELECT name, description, link FROM cv_projects"
    projects = await database.fetch_all(query)
    return {"projects": projects}