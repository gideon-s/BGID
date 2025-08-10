#!/usr/bin/env python3
"""
Seed script to populate the database with initial data
"""
from database import SessionLocal, engine
from models import Base, Player, Room, Item, Npc
from datetime import datetime

def seed_database():
    # Create database tables
    Base.metadata.create_all(bind=engine)
    
    # Create a database session
    db = SessionLocal()
    
    try:
        # Check if data already exists
        existing_room = db.query(Room).first()
        if existing_room:
            print("Database already seeded. Skipping...")
            return
        
        print("Seeding database with initial data...")
        
        # Create a room
        tavern = Room(
            name="The Rusty Tavern",
            description="A cozy tavern with a crackling fireplace, wooden tables, and the smell of ale in the air. Travelers gather here to share stories and rest their weary bones.",
            is_accessible=True
        )
        db.add(tavern)
        db.flush()  # Flush to get the ID
        
        # Create a player
        hero = Player(
            name="Hero",
            health=100,
            max_health=100,
            level=1,
            experience=0,
            room_id=tavern.id
        )
        db.add(hero)
        db.flush()
        
        # Create an item
        sword = Item(
            name="Iron Sword",
            description="A well-crafted iron sword with a leather-wrapped hilt. It has seen many battles but remains sharp and reliable.",
            item_type="weapon",
            value=50,
            room_id=tavern.id,
            player_id=None,
            is_equipped=False
        )
        db.add(sword)
        
        # Create an NPC
        innkeeper = Npc(
            name="Old Tom",
            description="A weathered innkeeper with kind eyes and a warm smile. He's been running this tavern for decades and knows all the local gossip.",
            npc_type="merchant",
            health=100,
            max_health=100,
            room_id=tavern.id,
            is_friendly=True
        )
        db.add(innkeeper)
        
        # Commit all changes
        db.commit()
        
        print("Database seeded successfully!")
        print(f"Created room: {tavern.name} (ID: {tavern.id})")
        print(f"Created player: {hero.name} (ID: {hero.id})")
        print(f"Created item: {sword.name} (ID: {sword.id})")
        print(f"Created NPC: {innkeeper.name} (ID: {innkeeper.id})")
        
    except Exception as e:
        print(f"Error seeding database: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def clear_database():
    """Clear all data from the database"""
    db = SessionLocal()
    try:
        print("Clearing database...")
        db.query(Item).delete()
        db.query(Npc).delete()
        db.query(Player).delete()
        db.query(Room).delete()
        db.commit()
        print("Database cleared successfully!")
    except Exception as e:
        print(f"Error clearing database: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        clear_database()
    else:
        seed_database()
