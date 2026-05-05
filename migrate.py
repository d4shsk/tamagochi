import os
from sqlalchemy import create_engine, text
from database import SessionLocal, Team, PetStage, DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}) if DATABASE_URL.startswith("sqlite") else create_engine(DATABASE_URL)

def run_migration():
    print("Starting migration...")
    # 1. Add column if not exists
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE teams ADD COLUMN level INTEGER DEFAULT 1"))
            print("Added 'level' column to 'teams' table.")
    except Exception as e:
        print("Column 'level' might already exist or error:", e)

    # 2. Update levels and rollback stage to EGG for users who advanced too fast
    db = SessionLocal()
    try:
        teams = db.query(Team).all()
        for team in teams:
            # Only migrate old teams that advanced without having a proper level yet
            if team.level is None or team.level == 1:
                if team.pet_stage == PetStage.BABY:
                    team.level = 2
                    team.pet_stage = PetStage.EGG
                elif team.pet_stage == PetStage.TEEN:
                    team.level = 3
                    team.pet_stage = PetStage.EGG
                elif team.pet_stage == PetStage.ADULT:
                    team.level = 4
                    team.pet_stage = PetStage.EGG
                else:
                    if team.level is None:
                        team.level = 1
        db.commit()
        print("Data migration completed successfully.")
    except Exception as e:
        db.rollback()
        print("Error during data migration:", e)
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
