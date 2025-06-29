#!/usr/bin/env python3
"""
FB2 to UTF-8 text converter
Converts FB2 files to clean UTF-8 text files
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Optional


def clean_text(text: str) -> str:
    """
    Clean text: replace typographic quotes/dashes, remove double spaces
    
    Args:
        text: Input text
        
    Returns:
        Cleaned text
    """
    # Replace typographic quotes with standard quotes
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")

    # Replace long dashes with standard dash
    text = text.replace('—', '-')
    text = text.replace('–', '-')

    # Replace non-breaking spaces with regular spaces
    text = text.replace('\u00A0', ' ')

    # Remove double spaces
    text = re.sub(r' +', ' ', text)

    # Clean up spaces around newlines
    text = re.sub(r' *\n *', '\n', text)

    return text


def extract_text_from_fb2(fb2_path: str) -> str:
    """
    Extract text content from FB2 file
    
    Args:
        fb2_path: Path to FB2 file
        
    Returns:
        Extracted text as string
    """
    try:
        # Parse FB2 file
        tree = ET.parse(fb2_path)
        root = tree.getroot()

        # FB2 namespace
        ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}

        # Track chapters
        chapter_num = 0
        output_parts = []

        # Find all body elements
        bodies = root.findall('.//fb:body', ns)

        for body in bodies:
            # Find sections (chapters)
            sections = body.findall('.//fb:section', ns)
            for section in sections:
                # Extract paragraphs from this section
                paragraphs = []

                # Check if this is a chapter-level section with title
                title_elem = section.find('.//fb:title', ns)
                if title_elem is not None:
                    # This looks like a chapter
                    chapter_num += 1

                    # Extract title text
                    title_parts = []
                    for p in title_elem.findall('.//fb:p', ns):
                        if p.text:
                            print('p.text', p.text)
                            title_parts.append(p.text.strip())
                        else:
                            p = ''.join(p.itertext())
                            title_parts.append(p.strip())
                    print('title_parts', title_parts)
                    title_text = ' '.join(title_parts)
                    print('title_text', title_text)
                    # Remove chapter number prefix (e.g., "1. ", "2. ", "CHAPTER ONE", etc.)
                    if title_text:
                        # Remove numeric prefix
                        title_text = re.sub(r'^\d+\.\s*', '', title_text)
                        # Remove "CHAPTER ONE", "CHAPTER TWO", etc.
                        title_text = re.sub(
                            r'^CHAPTER\s+(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY|TWENTY-ONE|TWENTY-TWO|TWENTY-THREE|TWENTY-FOUR|TWENTY-FIVE)\s*',
                            '', title_text, flags=re.IGNORECASE)
                        # Remove "CHAPTER 1", "CHAPTER 2", etc.
                        title_text = re.sub(r'^CHAPTER\s+\d+\s*', '', title_text, flags=re.IGNORECASE)
                    print('title_text2', title_text)
                    # Combine chapter marker with title on same line
                    if title_text:
                        paragraphs.append(f"### CHAPTER_{chapter_num:02d} {title_text}\n")
                    else:
                        paragraphs.append(f"### CHAPTER_{chapter_num:02d}\n")

                # Find all paragraphs not in title
                for p_elem in section.findall('.//fb:p', ns):
                    # Check if this paragraph is not in a title
                    in_title = False
                    for title in section.findall('.//fb:title', ns):
                        if p_elem in title.findall('.//fb:p', ns):
                            in_title = True
                            break

                    if in_title:
                        continue

                    # Build paragraph text with proper handling of emphasis and other inline elements
                    paragraph_text = ''
                    if p_elem.text:
                        paragraph_text += p_elem.text

                    for child in p_elem:
                        # Add child text (like emphasis content)
                        if child.text:
                            paragraph_text += child.text
                        # Add tail text (text after the child element)
                        if child.tail:
                            paragraph_text += child.tail

                    # Clean and add paragraph
                    paragraph_text = paragraph_text.strip()
                    if paragraph_text:
                        paragraphs.append(paragraph_text)

                if paragraphs:
                    # Add all paragraphs to output
                    output_parts.extend(paragraphs)

        # Join all parts with literal \n\n, but handle chapter titles specially
        result_parts = []
        prev_was_chapter = False

        for i, part in enumerate(output_parts):
            if part.startswith('### CHAPTER_'):
                # Add chapter with real newline before (if not first) and after
                if result_parts:
                    # Add real newline before new chapter (no \n\n)
                    result_parts.append('\n' + part.rstrip() + '\n')
                else:
                    result_parts.append(part.rstrip() + '\n')
                prev_was_chapter = True
            else:
                # Regular paragraphs
                if result_parts and not prev_was_chapter:
                    result_parts.append(r'\n\n' + part)
                else:
                    result_parts.append(part)
                prev_was_chapter = False

        full_text = ''.join(result_parts)

        # Clean up text
        full_text = clean_text(full_text)

        # Remove leading/trailing whitespace
        full_text = full_text.strip()

        return full_text

    except ET.ParseError as e:
        print(f"Error parsing FB2 file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading FB2 file: {e}")
        sys.exit(1)


def convert_fb2_to_txt(fb2_path: str, output_path: Optional[str] = None) -> str:
    """
    Convert FB2 file to UTF-8 text file
    
    Args:
        fb2_path: Path to input FB2 file
        output_path: Optional output path (defaults to same name with .txt extension)
        
    Returns:
        Path to output file
    """
    # Check if input file exists
    if not os.path.exists(fb2_path):
        print(f"Error: File not found: {fb2_path}")
        sys.exit(1)

    # Generate output path if not provided
    if output_path is None:
        base_name = os.path.splitext(fb2_path)[0]
        output_path = f"{base_name}.txt"

    print(f"Converting: {fb2_path}")
    print(f"Output: {output_path}")

    # Extract text
    text = extract_text_from_fb2(fb2_path)

    # Write to UTF-8 text file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"Successfully converted to: {output_path}")
        print(f"File size: {os.path.getsize(output_path):,} bytes")
        return output_path
    except Exception as e:
        print(f"Error writing output file: {e}")
        sys.exit(1)


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python convert_fb2_to_txt.py <fb2_file> [output_file]")
        print("\nExample:")
        print("  python convert_fb2_to_txt.py books_data/Harry_Potter.fb2")
        print("  python convert_fb2_to_txt.py books_data/Harry_Potter.fb2 output.txt")
        sys.exit(1)

    fb2_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    convert_fb2_to_txt(fb2_path, output_path)


if __name__ == "__main__":
    main()
