from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy import func, or_

from app import csrf
from app.api.auth import api_login_required
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

api_topics_collections = Blueprint('api_topics_collections', __name__)


# API маршруты для тем (Topics)
@api_topics_collections.route('/topics', methods=['GET'])
@api_login_required
def get_topics():
    """Получение списка тем с фильтрацией и пагинацией"""
    # Параметры запроса
    search = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Базовый запрос
    query = db.select(Topic)

    # Применение поиска
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Topic.name.ilike(search_term),
                Topic.description.ilike(search_term)
            )
        )

    # Общее количество
    count_query = db.select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()

    # Применение пагинации
    query = query.order_by(Topic.name).limit(per_page).offset((page - 1) * per_page)

    # Выполнение запроса
    topics = db.session.execute(query).scalars().all()

    # Получение дополнительной информации для каждой темы
    topics_list = []
    for topic in topics:
        # Количество слов в теме
        word_count = db.session.query(func.count(TopicWord.id)).filter_by(topic_id=topic.id).scalar()

        # Количество слов в изучении
        user_word_ids = db.session.query(UserWord.word_id).filter_by(user_id=current_user.id).all()
        user_word_ids = [id[0] for id in user_word_ids]

        # Проверка, сколько слов из темы уже изучается пользователем
        topic_word_ids = db.session.query(TopicWord.word_id).filter_by(topic_id=topic.id).all()
        topic_word_ids = [id[0] for id in topic_word_ids]
        words_in_study = len(set(topic_word_ids).intersection(set(user_word_ids)))

        topics_list.append({
            'id': topic.id,
            'name': topic.name,
            'description': topic.description,
            'word_count': word_count,
            'words_in_study': words_in_study
        })

    # Расчет общего количества страниц
    total_pages = (total + per_page - 1) // per_page

    return jsonify({
        'topics': topics_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@api_topics_collections.route('/topics/<int:topic_id>', methods=['GET'])
@api_login_required
def get_topic(topic_id):
    """Получение детальной информации о теме"""
    topic = Topic.query.get_or_404(topic_id)

    # Количество слов в теме
    word_count = db.session.query(func.count(TopicWord.id)).filter_by(topic_id=topic.id).scalar()

    # Получение слов, связанных с темой
    topic_words_query = db.select(CollectionWords).join(
        TopicWord, CollectionWords.id == TopicWord.word_id
    ).where(
        TopicWord.topic_id == topic_id
    ).order_by(CollectionWords.english_word)

    words = db.session.execute(topic_words_query).scalars().all()

    # Получение статусов слов для пользователя
    words_list = []
    for word in words:
        status = current_user.get_word_status(word.id)
        words_list.append({
            'id': word.id,
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level,
            'status': status
        })

    # Получение связанных коллекций
    related_collections_query = db.select(Collection).join(
        CollectionWordLink, Collection.id == CollectionWordLink.collection_id
    ).join(
        TopicWord, CollectionWordLink.word_id == TopicWord.word_id
    ).where(
        TopicWord.topic_id == topic_id
    ).group_by(Collection.id).order_by(Collection.name)

    related_collections = db.session.execute(related_collections_query).scalars().all()
    collections_list = [{
        'id': collection.id,
        'name': collection.name,
        'description': collection.description
    } for collection in related_collections]

    # Информация о создателе
    creator = None
    if topic.created_by:
        from app.auth.models import User
        user = User.query.get(topic.created_by)
        if user:
            creator = {
                'id': user.id,
                'username': user.username
            }

    return jsonify({
        'id': topic.id,
        'name': topic.name,
        'description': topic.description,
        'word_count': word_count,
        'words': words_list,
        'related_collections': collections_list,
        'creator': creator
    })


@api_topics_collections.route('/topics/<int:topic_id>/words', methods=['GET'])
@api_login_required
def get_topic_words(topic_id):
    """Получение слов, связанных с темой"""
    # Проверка существования темы
    topic = Topic.query.get_or_404(topic_id)

    # Параметры запроса
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Базовый запрос для слов темы
    query = db.select(CollectionWords).join(
        TopicWord, CollectionWords.id == TopicWord.word_id
    ).where(
        TopicWord.topic_id == topic_id
    ).order_by(CollectionWords.english_word)

    # Общее количество
    count_query = db.select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()

    # Применение пагинации
    query = query.limit(per_page).offset((page - 1) * per_page)

    # Выполнение запроса
    words = db.session.execute(query).scalars().all()

    # Форматирование ответа
    words_list = []
    for word in words:
        status = current_user.get_word_status(word.id)
        words_list.append({
            'id': word.id,
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level,
            'status': status
        })

    # Расчет общего количества страниц
    total_pages = (total + per_page - 1) // per_page

    return jsonify({
        'topic_id': topic_id,
        'topic_name': topic.name,
        'words': words_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@api_topics_collections.route('/topics/<int:topic_id>/add-to-study', methods=['POST'])
@csrf.exempt
@api_login_required
def add_topic_to_study(topic_id):
    """Добавление всех слов темы в список изучения"""
    # Проверка существования темы
    topic = Topic.query.get_or_404(topic_id)

    # Получение слов темы
    topic_word_ids = db.session.query(TopicWord.word_id).filter_by(topic_id=topic_id).all()
    topic_word_ids = [id[0] for id in topic_word_ids]

    # Получение слов, которые уже изучаются
    user_word_ids = db.session.query(UserWord.word_id).filter_by(user_id=current_user.id).all()
    user_word_ids = [id[0] for id in user_word_ids]

    # Определение слов для добавления
    words_to_add = set(topic_word_ids) - set(user_word_ids)

    # Добавление слов в изучение
    added_count = 0
    for word_id in words_to_add:
        user_word = UserWord(user_id=current_user.id, word_id=word_id)
        db.session.add(user_word)
        added_count += 1

    # Create or find deck for this topic
    if added_count > 0:
        from app.study.models import QuizDeck, QuizDeckWord
        from sqlalchemy import func

        deck_title = f"Топик: {topic.name}"
        topic_deck = QuizDeck.query.filter_by(
            user_id=current_user.id,
            title=deck_title
        ).first()

        if not topic_deck:
            topic_deck = QuizDeck(
                title=deck_title,
                description=f"Слова из топика '{topic.name}'",
                user_id=current_user.id,
                is_public=False
            )
            db.session.add(topic_deck)
            db.session.flush()

        # Add all new words to deck
        for word_id in words_to_add:
            # Check if word already in deck
            existing = QuizDeckWord.query.filter_by(
                deck_id=topic_deck.id,
                word_id=word_id
            ).first()

            if not existing:
                max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
                    QuizDeckWord.deck_id == topic_deck.id
                ).scalar() or 0

                deck_word = QuizDeckWord(
                    deck_id=topic_deck.id,
                    word_id=word_id,
                    order_index=max_order + 1
                )
                db.session.add(deck_word)

    try:
        db.session.commit()

        # Синхронизация мастер-колод
        if added_count > 0:
            from app.study.routes import sync_master_decks
            sync_master_decks(current_user.id)
            db.session.commit()

        return jsonify({
            'success': True,
            'topic_id': topic_id,
            'topic_name': topic.name,
            'added_count': added_count,
            'total_count': len(topic_word_ids)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


# API маршруты для коллекций (Collections)
@api_topics_collections.route('/collections', methods=['GET'])
@api_login_required
def get_collections():
    """Получение списка коллекций с фильтрацией и пагинацией"""
    # Параметры запроса
    search = request.args.get('search')
    topic_id = request.args.get('topic_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Базовый запрос
    query = db.select(Collection)

    # Применение фильтра по теме
    if topic_id:
        query = query.join(
            CollectionWordLink, Collection.id == CollectionWordLink.collection_id
        ).join(
            TopicWord, CollectionWordLink.word_id == TopicWord.word_id
        ).where(
            TopicWord.topic_id == topic_id
        ).group_by(Collection.id)

    # Применение поиска
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Collection.name.ilike(search_term),
                Collection.description.ilike(search_term)
            )
        )

    # Общее количество
    count_query = db.select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()

    # Применение пагинации
    query = query.order_by(Collection.name).limit(per_page).offset((page - 1) * per_page)

    # Выполнение запроса
    collections = db.session.execute(query).scalars().all()

    # Форматирование ответа
    collections_list = []
    for collection in collections:
        # Количество слов в коллекции
        word_count = db.session.query(func.count(CollectionWordLink.id)).filter_by(collection_id=collection.id).scalar()

        # Получение слов, которые уже изучаются
        user_word_ids = db.session.query(UserWord.word_id).filter_by(user_id=current_user.id).all()
        user_word_ids = [id[0] for id in user_word_ids]

        # Определение слов коллекции, которые уже изучаются
        collection_word_ids = db.session.query(CollectionWordLink.word_id).filter_by(collection_id=collection.id).all()
        collection_word_ids = [id[0] for id in collection_word_ids]
        words_in_study = len(set(collection_word_ids).intersection(set(user_word_ids)))

        # Получение связанных тем
        # Находим все темы слов, входящих в коллекцию
        topic_ids = db.session.query(TopicWord.topic_id).join(
            CollectionWordLink, TopicWord.word_id == CollectionWordLink.word_id
        ).filter(
            CollectionWordLink.collection_id == collection.id
        ).distinct().all()

        topic_ids = [id[0] for id in topic_ids]
        topics = Topic.query.filter(Topic.id.in_(topic_ids)).all()

        topics_list = [{
            'id': topic.id,
            'name': topic.name
        } for topic in topics]

        collections_list.append({
            'id': collection.id,
            'name': collection.name,
            'description': collection.description,
            'created_by': collection.created_by,
            'created_at': collection.created_at.isoformat() if collection.created_at else None,
            'word_count': word_count,
            'words_in_study': words_in_study,
            'topics': topics_list
        })

    # Расчет общего количества страниц
    total_pages = (total + per_page - 1) // per_page

    return jsonify({
        'collections': collections_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@api_topics_collections.route('/collections/<int:collection_id>', methods=['GET'])
@api_login_required
def get_collection(collection_id):
    """Получение детальной информации о коллекции"""
    collection = Collection.query.get_or_404(collection_id)

    # Получение слов коллекции
    collection_words_query = db.select(CollectionWords).join(
        CollectionWordLink, CollectionWords.id == CollectionWordLink.word_id
    ).where(
        CollectionWordLink.collection_id == collection_id
    ).order_by(CollectionWords.english_word)

    words = db.session.execute(collection_words_query).scalars().all()

    # Получение статусов слов
    words_list = []
    for word in words:
        status = current_user.get_word_status(word.id)

        # Получение тем для каждого слова
        word_topics = Topic.query.join(
            TopicWord, Topic.id == TopicWord.topic_id
        ).filter(
            TopicWord.word_id == word.id
        ).all()

        word_topics_list = [{
            'id': topic.id,
            'name': topic.name
        } for topic in word_topics]

        words_list.append({
            'id': word.id,
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level,
            'status': status,
            'topics': word_topics_list
        })

    # Получение связанных тем
    topic_ids = db.session.query(TopicWord.topic_id).join(
        CollectionWordLink, TopicWord.word_id == CollectionWordLink.word_id
    ).filter(
        CollectionWordLink.collection_id == collection_id
    ).distinct().all()

    topic_ids = [id[0] for id in topic_ids]
    topics = Topic.query.filter(Topic.id.in_(topic_ids)).all()

    topics_list = [{
        'id': topic.id,
        'name': topic.name,
        'description': topic.description
    } for topic in topics]

    # Информация о создателе
    creator = None
    if collection.created_by:
        from app.auth.models import User
        user = User.query.get(collection.created_by)
        if user:
            creator = {
                'id': user.id,
                'username': user.username
            }

    return jsonify({
        'id': collection.id,
        'name': collection.name,
        'description': collection.description,
        'created_by': collection.created_by,
        'created_at': collection.created_at.isoformat() if collection.created_at else None,
        'creator': creator,
        'word_count': len(words),
        'words': words_list,
        'topics': topics_list
    })


@api_topics_collections.route('/collections/<int:collection_id>/words', methods=['GET'])
@api_login_required
def get_collection_words(collection_id):
    """Получение слов коллекции"""
    # Проверка существования коллекции
    collection = Collection.query.get_or_404(collection_id)

    # Параметры запроса
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Базовый запрос для слов коллекции
    query = db.select(CollectionWords).join(
        CollectionWordLink, CollectionWords.id == CollectionWordLink.word_id
    ).where(
        CollectionWordLink.collection_id == collection_id
    ).order_by(CollectionWords.english_word)

    # Общее количество
    count_query = db.select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()

    # Применение пагинации
    query = query.limit(per_page).offset((page - 1) * per_page)

    # Выполнение запроса
    words = db.session.execute(query).scalars().all()

    # Форматирование ответа
    words_list = []
    for word in words:
        status = current_user.get_word_status(word.id)
        words_list.append({
            'id': word.id,
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level,
            'status': status
        })

    # Расчет общего количества страниц
    total_pages = (total + per_page - 1) // per_page

    return jsonify({
        'collection_id': collection_id,
        'collection_name': collection.name,
        'words': words_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@api_topics_collections.route('/collections/<int:collection_id>/add-to-study', methods=['POST'])
@csrf.exempt
@api_login_required
def add_collection_to_study(collection_id):
    """Добавление всех слов коллекции в список изучения"""
    # Проверка существования коллекции
    collection = Collection.query.get_or_404(collection_id)

    # Получение слов коллекции
    collection_word_ids = db.session.query(CollectionWordLink.word_id).filter_by(collection_id=collection_id).all()
    collection_word_ids = [id[0] for id in collection_word_ids]

    # Получение слов, которые уже изучаются
    user_word_ids = db.session.query(UserWord.word_id).filter_by(user_id=current_user.id).all()
    user_word_ids = [id[0] for id in user_word_ids]

    # Определение слов для добавления
    words_to_add = set(collection_word_ids) - set(user_word_ids)

    # Добавление слов в изучение
    added_count = 0
    for word_id in words_to_add:
        user_word = UserWord(user_id=current_user.id, word_id=word_id)
        db.session.add(user_word)
        added_count += 1

    # Create or find deck for this collection
    if added_count > 0:
        from app.study.models import QuizDeck, QuizDeckWord
        from sqlalchemy import func

        deck_title = f"Коллекция: {collection.name}"
        collection_deck = QuizDeck.query.filter_by(
            user_id=current_user.id,
            title=deck_title
        ).first()

        if not collection_deck:
            collection_deck = QuizDeck(
                title=deck_title,
                description=f"Слова из коллекции '{collection.name}'",
                user_id=current_user.id,
                is_public=False
            )
            db.session.add(collection_deck)
            db.session.flush()

        # Add all new words to deck
        for word_id in words_to_add:
            # Check if word already in deck
            existing = QuizDeckWord.query.filter_by(
                deck_id=collection_deck.id,
                word_id=word_id
            ).first()

            if not existing:
                max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
                    QuizDeckWord.deck_id == collection_deck.id
                ).scalar() or 0

                deck_word = QuizDeckWord(
                    deck_id=collection_deck.id,
                    word_id=word_id,
                    order_index=max_order + 1
                )
                db.session.add(deck_word)

    try:
        db.session.commit()

        # Синхронизация мастер-колод
        if added_count > 0:
            from app.study.routes import sync_master_decks
            sync_master_decks(current_user.id)
            db.session.commit()

        return jsonify({
            'success': True,
            'collection_id': collection_id,
            'collection_name': collection.name,
            'added_count': added_count,
            'total_count': len(collection_word_ids)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500


# API для работы со словами в контексте тем и коллекций
@api_topics_collections.route('/words/<int:word_id>/topics', methods=['GET'])
@api_login_required
def get_word_topics(word_id):
    """Получение тем, связанных со словом"""
    # Проверка существования слова
    word = CollectionWords.query.get_or_404(word_id)

    # Получение тем слова
    topics = Topic.query.join(
        TopicWord, Topic.id == TopicWord.topic_id
    ).filter(
        TopicWord.word_id == word_id
    ).all()

    topics_list = [{
        'id': topic.id,
        'name': topic.name,
        'description': topic.description
    } for topic in topics]

    return jsonify({
        'word_id': word_id,
        'english_word': word.english_word,
        'topics': topics_list
    })


@api_topics_collections.route('/words/<int:word_id>/collections', methods=['GET'])
@api_login_required
def get_word_collections(word_id):
    """Получение коллекций, содержащих слово"""
    # Проверка существования слова
    word = CollectionWords.query.get_or_404(word_id)

    # Получение коллекций слова
    collections = Collection.query.join(
        CollectionWordLink, Collection.id == CollectionWordLink.collection_id
    ).filter(
        CollectionWordLink.word_id == word_id
    ).all()

    collections_list = [{
        'id': collection.id,
        'name': collection.name,
        'description': collection.description
    } for collection in collections]

    return jsonify({
        'word_id': word_id,
        'english_word': word.english_word,
        'collections': collections_list
    })
