import aiosqlite
import logging
from typing import Any, Optional, Sequence, List, Tuple
from dataclasses import dataclass
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions.session import Session
from google.genai import types
from typing_extensions import override

logger = logging.getLogger(__name__)

@dataclass
class UserProfile:
    """Dataclass representing the explicit user profile details."""
    user_id: str
    home_city: Optional[str] = None
    budget_tier: Optional[str] = None
    dietary_restrictions: Optional[str] = None

class UserProfileRepository:
    """Handles SQLite database access for user profiles and preference weights."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialized = False

    async def init_db(self):
        """Initializes the SQLite tables if they do not exist."""
        if self._initialized:
            return
        logger.info(f"Initializing memory database at {self.db_path}")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    home_city TEXT,
                    budget_tier TEXT,
                    dietary_restrictions TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_preference_weights (
                    user_id TEXT,
                    category TEXT,
                    weight REAL,
                    PRIMARY KEY (user_id, category)
                )
            """)
            await db.commit()
        self._initialized = True

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetches the user profile from the database."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT home_city, budget_tier, dietary_restrictions FROM user_profiles WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return UserProfile(
                        user_id=user_id,
                        home_city=row[0],
                        budget_tier=row[1],
                        dietary_restrictions=row[2]
                    )
        return None

    async def save_profile(self, profile: UserProfile):
        """Saves or updates the user profile in the database."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_profiles (user_id, home_city, budget_tier, dietary_restrictions)
                VALUES (?, ?, ?, ?)
            """, (profile.user_id, profile.home_city, profile.budget_tier, profile.dietary_restrictions))
            await db.commit()

    async def get_weights(self, user_id: str) -> List[Tuple[str, float]]:
        """Fetches all preference weights for a user."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT category, weight FROM user_preference_weights WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                return await cursor.fetchall()

    async def get_weight(self, user_id: str, category: str) -> float:
        """Fetches the weight for a specific category, defaulting to 1.0."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT weight FROM user_preference_weights WHERE user_id = ? AND category = ?",
                (user_id, category)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 1.0

    async def save_weight(self, user_id: str, category: str, weight: float):
        """Saves or updates a preference weight in the database."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_preference_weights (user_id, category, weight)
                VALUES (?, ?, ?)
            """, (user_id, category, weight))
            await db.commit()


class SQLiteMemoryService(BaseMemoryService):
    """Custom memory service using SQLite to persist user profile and preference weights."""
    
    def __init__(self, db_path: str):
        self.repository = UserProfileRepository(db_path)

    @override
    async def add_session_to_memory(self, session: Session) -> None:
        user_id = session.user_id
        state = session.state
        
        logger.info(f"Adding session {session.id} to memory for user {user_id}")
        
        # 1. Update explicit preferences from session state
        explicit = state.get("explicit_preferences", {})
        if explicit:
            current_profile = await self.repository.get_profile(user_id)
            
            # Merge logic: prioritize new values, fallback to current
            home_city = explicit.get("home_city") or (current_profile.home_city if current_profile else None)
            budget_tier = explicit.get("budget_tier") or (current_profile.budget_tier if current_profile else None)
            dietary_restrictions = explicit.get("dietary_restrictions") or (current_profile.dietary_restrictions if current_profile else None)
            
            new_profile = UserProfile(
                user_id=user_id,
                home_city=home_city,
                budget_tier=budget_tier,
                dietary_restrictions=dietary_restrictions
            )
            logger.info(f"Updating profile for user {user_id}: {new_profile}")
            await self.repository.save_profile(new_profile)

        # 2. Update implicit preferences (rejections) with weight decay
        rejected = state.get("rejected_categories", [])
        if rejected:
            logger.info(f"Processing rejections for user {user_id}: {rejected}")
            for category in rejected:
                current_weight = await self.repository.get_weight(user_id, category)
                new_weight = current_weight * 0.5
                logger.info(f"Decaying weight for user {user_id}, category {category}: {current_weight} -> {new_weight}")
                await self.repository.save_weight(user_id, category, new_weight)

    @override
    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        logger.info(f"Searching memory for user {user_id}, query: '{query}'")
        
        profile = await self.repository.get_profile(user_id)
        weights = await self.repository.get_weights(user_id)

        # Construct textual summary
        summary_parts = []
        if profile:
            profile_str = "User Profile: "
            if profile.home_city: profile_str += f"Home City: {profile.home_city}, "
            if profile.budget_tier: profile_str += f"Budget: {profile.budget_tier}, "
            if profile.dietary_restrictions: profile_str += f"Dietary Restrictions: {profile.dietary_restrictions}, "
            summary_parts.append(profile_str.rstrip(", "))
            
        if weights:
            pref_str = "User Preference Weights (lower weight means less preferred): "
            pref_str += ", ".join([f"{cat}: {weight:.2f}" for cat, weight in weights])
            summary_parts.append(pref_str)

        if not summary_parts:
            logger.info("No memory found for user.")
            return SearchMemoryResponse(memories=[])

        full_summary = "\n".join(summary_parts)
        logger.info(f"Retrieved memory summary:\n{full_summary}")
        
        # Wrap in MemoryEntry
        content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=full_summary)]
        )
        
        entry = MemoryEntry(
            content=content,
            author="System",
            id=f"profile-{user_id}"
        )
        
        return SearchMemoryResponse(memories=[entry])
