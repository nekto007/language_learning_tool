"""Small, authored A1 examples for the public landing page."""
from random import choice


PREVIEWS = (
    dict(id='intro_am', prompt='I ___ Anna.', instruction='Нужно представиться: «Я Анна». Какое слово подходит?',
         options=('am', 'is', 'are'), correct='am',
         explanation='С I используем am: I am Anna. — «Я Анна».'),
    dict(id='name_is', prompt='My name ___ Alex.', instruction='Нужно сказать: «Меня зовут Алекс». Выберите слово.',
         options=('am', 'is', 'are'), correct='is',
         explanation='My name — «моё имя». Здесь используем is: My name is Alex. — «Меня зовут Алекс».'),
    dict(id='you_are', prompt='You ___ my friend.', instruction='Нужно сказать: «Ты мой друг». Выберите слово.',
         options=('am', 'is', 'are'), correct='are',
         explanation='С you используем are: You are my friend. — «Ты мой друг».'),
    dict(id='she_is', prompt='She ___ a teacher.', instruction='Нужно сказать: «Она учитель». Выберите слово.',
         options=('am', 'is', 'are'), correct='is',
         explanation='С she используем is: She is a teacher. — «Она учитель».'),
    dict(id='they_are', prompt='They ___ at home.', instruction='Нужно сказать: «Они дома». Выберите слово.',
         options=('am', 'is', 'are'), correct='are',
         explanation='С they используем are: They are at home. — «Они дома».'),
    dict(id='have_cat', prompt='I ___ a cat.', instruction='Нужно сказать: «У меня есть кот». Выберите слово.',
         options=('have', 'has', 'am'), correct='have',
         explanation='I have означает «у меня есть»: I have a cat. — «У меня есть кот».'),
    dict(id='has_dog', prompt='He ___ a dog.', instruction='Нужно сказать: «У него есть собака». Выберите слово.',
         options=('have', 'has', 'is'), correct='has',
         explanation='С he используем has: He has a dog. — «У него есть собака».'),
    dict(id='article_apple', prompt='It is ___ apple.', instruction='Нужно сказать: «Это яблоко». Какой артикль подходит?',
         options=('a', 'an', 'am'), correct='an',
         explanation='Apple начинается с гласного звука, поэтому нужен an: It is an apple. — «Это яблоко».'),
    dict(id='plural_books', prompt='One book, two ___.', instruction='Нужно сказать: «Одна книга, две книги». Выберите форму слова.',
         options=('book', 'books', 'bookes'), correct='books',
         explanation='Во множественном числе к book добавляем -s: two books — «две книги».'),
    dict(id='can_swim', prompt='I can ___.', instruction='Нужно сказать: «Я умею плавать». Выберите форму глагола.',
         options=('swim', 'swims', 'to swim'), correct='swim',
         explanation='После can используем глагол без to и без -s: I can swim. — «Я умею плавать».'),
)
PREVIEWS_BY_ID = {item['id']: item for item in PREVIEWS}


def pick_preview():
    return choice(PREVIEWS)
