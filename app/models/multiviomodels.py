from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, EmailStr, Field, HttpUrl

class MultivioUserBase(BaseModel):
    firebase_uid: str = Field(..., description="Firebase User ID")
    email: EmailStr
    username: Optional[str] = None
    phone_number: Optional[str] = None
    recovery_email: Optional[EmailStr] = None
    profile_image_url: Optional[HttpUrl] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioSubscriptionPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str  # Free, Pro, Business, Enterprise
    price: float
    max_social_accounts: int
    max_scheduled_posts: int
    max_team_members: int
    features: List[str]
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioUserSubscription(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # Firebase UID
    plan_id: UUID
    status: str  # active, canceled, expired
    start_date: datetime
    end_date: Optional[datetime]
    payment_method: Optional[str]
    auto_renew: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioQuest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    quest_type: str = Field(..., description="daily, weekly, monthly, achievement")
    points: int = 0
    requirements: Dict[str, int] = Field(default_factory=dict)
    reward_type: str
    reward_value: str
    is_active: bool = True
    target_platforms: List[str] = Field(default_factory=list)
    post_count: int = 0
    schedule_start: Optional[datetime] = None
    schedule_end: Optional[datetime] = None
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioQuestProgress(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    quest_id: UUID
    user_id: str
    progress: Dict[str, int] = Field(default_factory=dict)
    status: str = "not_started"  # not_started, in_progress, completed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioQuestPosts(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    quest_id: UUID
    user_id: str  # Firebase UID
    content: str
    platform: str  # facebook, twitter, etc.
    media_urls: List[str] = []
    scheduled_time: Optional[datetime] = None
    status: str = "draft"  # draft, scheduled, published, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioUserSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # Firebase UID
    session_token: str
    ip_address: str
    user_agent: str
    last_activity: datetime
    expires_at: datetime
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioApiUsage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # Firebase UID
    platform: str  # facebook, twitter, linkedin, etc.
    endpoint: str
    request_count: int = 0
    last_request: datetime
    reset_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioUserReward(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # Firebase UID
    reward_type: str  # points, badge, feature
    reward_value: str
    source: str  # quest, achievement, promotion
    source_id: Optional[UUID]  # reference to quest or achievement
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioTeam(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    owner_id: str  # Firebase UID
    description: Optional[str]
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioTeamMember(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    team_id: UUID
    user_id: str  # Firebase UID
    role: str  # owner, admin, member
    permissions: List[str]
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class MultivioAuditLog(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # Firebase UID
    action: str
    entity_type: str  # user, subscription, quest, etc.
    entity_id: str
    changes: Dict[str, dict]  # {"field": {"old": value, "new": value}}
    ip_address: str
    created_at: datetime = Field(default_factory=datetime.utcnow)