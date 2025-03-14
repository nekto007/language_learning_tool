# User Guide

This guide will help you effectively use all the features of the Language Learning Tool for learning English.

## Contents

- [Web Interface](#web-interface)
- [Working with Words](#working-with-words)
- [Managing Learning Statuses](#managing-learning-statuses)
- [Working with Books and Sources](#working-with-books-and-sources)
- [Exporting to Anki](#exporting-to-anki)
- [Using the Command Line](#using-the-command-line)
- [Usage Scenario Examples](#usage-scenario-examples)

## Web Interface

### Logging In

1. Start the web server using the command `flask run`
2. Open http://127.0.0.1:5000/ in your browser
3. Register or log in to the system

### Main Sections

- **Dashboard** (`/dashboard`): General statistics and list of books
- **Word List** (`/words`): View and manage words
- **Word Details** (`/word/<id>`): Detailed information about a word

## Working with Words

### Viewing Words

On the word list page you can:

1. **Filter words**:
   - By learning status (tabs at the top of the page)
   - By first letter (alphabetical navigation)
   - Using search (search bar)
   - By books (selecting a specific book)

2. **Sort words**:
   - By frequency of use (for words from a specific book)
   - Alphabetically
   - By learning status

3. **View details**:
   - Click on a word to go to its detailed page

### Detailed Word Information

The word page displays:

- English and Russian meanings
- Learning status
- Audio pronunciation availability
- Usage examples
- List of books where the word appears
- Links to external dictionaries and resources

## Managing Learning Statuses

Each word has one of the following statuses:

- **New (0)**: Unprocessed word
- **Known (1)**: Word that you already know
- **Queued (2)**: Word that you plan to learn
- **Active (3)**: Word that you are currently learning
- **Mastered (4)**: Fully learned word

### Changing Status

You can change the status:

1. **For a single word**:
   - On the list page: click the "Change Status" button and select a status
   - On the word page: use the "Change Status" panel

2. **For multiple words**:
   - Check the desired words in the list
   - Click "Bulk Actions" and select a status

## Working with Books and Sources

### Viewing the Book List

The dashboard displays a list of books with statistics:
- Total word count
- Unique word count
- Scraping date

### Viewing Words from a Book

1. Click on the book title on the dashboard
2. A list of words from this book will open, sorted by frequency of use

### Adding a New Book/Source

To add a new source, use the command line:
```bash
python main.py scrape https://example.com/book --pages 10 --book "Book Title"
```

## Exporting to Anki

### Creating Anki Cards

1. On the word list page, select words for export
2. Click "Bulk Actions" → "Create Anki Cards"
3. In the window that appears, configure:
   - Deck name
   - Card format
   - Inclusion of pronunciation and examples
   - Status update

4. Click "Export"
5. Import the downloaded `.apkg` file into Anki

### Card Formats

- **Basic**: Word → Translation
  - Front side: English word and pronunciation
  - Back side: translation and examples

### Card Template Configuration

The following template is used by default:

**Front side:**
```html
<div class="english">
    <strong>{{en}}</strong>
</div>

{{#sound_name}}
<div class="audio-container">
    {{sound_name}}
</div>
{{/sound_name}}
```

**Back side:**
```html
{{FrontSide}}

<hr id="answer">

<div class="russian">
    <span class="translation">{{ru}}</span>
</div>

{{#context}}
<div class="context">
    {{{context}}}
</div>
{{/context}}
```

## Using the Command Line

### Web Page Scraping

To collect words from a web page:

```bash
python main.py scrape https://example.com/text --pages 5 --book "Book Title"
```

Parameters:
- `--pages`: Number of pages to process
- `--book`: Book/source title

### Updating Book Statistics

```bash
python main.py update-book-stats
```

For a specific book:
```bash
python main.py update-book-stats --book-id 1
```

### Managing Word Statuses

```bash
# Mark words from a file as known
python main.py update-status --status 1 --file known_words.txt

# Mark words starting with a certain letter as queued
python main.py update-status --status 2 --pattern "a%"

# Mark a specific word as active
python main.py update-status --status 3 --word "example"
```

### Downloading Pronunciations

```bash
# Download pronunciations for words starting with "a"
python main.py download-pronunciations --pattern "a%" --browser safari

# Download pronunciations via API
python main.py api-download --api-key YOUR_API_KEY --update-status
```

### Viewing Status Statistics

```bash
python main.py status-stats

# Statistics for a specific book
python main.py status-stats --book "Book Title"
```

## Usage Scenario Examples

### Scenario 1: Processing a New Book

1. Collect words from the source:
   ```bash
   python main.py scrape https://example.com/book --pages 20 --book "New Book"
   ```

2. Mark known words:
   ```bash
   python main.py update-status --status 1 --file my_known_words.txt
   ```

3. Download pronunciations for new words:
   ```bash
   python main.py api-download --api-key YOUR_API_KEY
   ```

4. In the web interface, browse words from the book and add interesting ones to the learning queue

5. Export queued words to Anki

### Scenario 2: Daily Learning

1. Go to the web interface and open the list of words with "Queued" status

2. Select 10-20 words to learn today

3. Export them to Anki, selecting the option "Change status to 'Active'"

4. After studying in Anki, return to the web interface

5. Review words with "Active" status and change the status of those you've memorized to "Mastered"

### Scenario 3: Progress Analysis

1. Go to the dashboard to view overall statistics

2. Evaluate progress on individual books

3. Use the command line to get detailed statistics:
   ```bash
   python main.py status-stats
   ```

4. Analyze which sources contain the most known/unknown words