from app.utils.db import db
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime


class Book(db.Model):
    __tablename__ = 'book'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), unique=True, nullable=False)
    total_words = Column(Integer, default=0)
    unique_words = Column(Integer, default=0)
    scrape_date = Column(DateTime, default=datetime.utcnow)

    words = relationship("CollectionWords", secondary="word_book_link", back_populates="books")