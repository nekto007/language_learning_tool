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


def iter_fb2_blocks(body, namespace):
    """Yield heading/paragraph text once, preserving the XML document order.

    A title owns its descendant paragraphs, and a paragraph owns its inline
    text. Neither subtree is revisited, including when sections are nested.
    The iterative walk also avoids Python recursion for deep section trees.
    """
    stack = list(reversed(list(body)))
    while stack:
        node = stack.pop()
        if node.tag == namespace + 'title':
            paragraphs = [''.join(p.itertext()).strip() for p in node.iter(namespace + 'p')]
            text = ' '.join(part for part in paragraphs if part) if paragraphs else ''.join(node.itertext()).strip()
            yield 'heading', text
        elif node.tag == namespace + 'p':
            yield 'paragraph', ''.join(node.itertext()).strip()
        else:
            stack.extend(reversed(list(node)))


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

        namespace = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
        chapter_num = 0
        output_parts = []
        for body in root.findall('.//' + namespace + 'body'):
            for kind, text in iter_fb2_blocks(body, namespace):
                if kind == 'heading':
                    chapter_num += 1
                    # Preserve the existing chapter marker/title convention.
                    title_text = re.sub(r'^\d+\.\s*', '', text)
                    title_text = re.sub(
                        r'^CHAPTER\s+(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY|TWENTY-ONE|TWENTY-TWO|TWENTY-THREE|TWENTY-FOUR|TWENTY-FIVE)\s*',
                        '', title_text, flags=re.IGNORECASE)
                    title_text = re.sub(r'^CHAPTER\s+\d+\s*', '', title_text, flags=re.IGNORECASE)
                    output_parts.append(f"### CHAPTER_{chapter_num:02d}" + (f" {title_text}" if title_text else '') + "\n")
                elif text:
                    output_parts.append(text)

        # Join all parts with literal \n\n, but handle chapter titles specially
        result_parts = []
        prev_was_chapter = False

        for part in output_parts:
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
                    result_parts.append('\n\n' + part)
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
