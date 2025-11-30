/**
 * SRS Queue - Unified client-side queue management for spaced repetition.
 *
 * Rating Scale (1-2-3):
 *   1 - Не знаю (Don't know): Show again in 1-2 cards
 *   2 - Сомневаюсь (Doubt): Show again in 3-5 cards
 *   3 - Знаю (Know): Remove from session
 *
 * Max 3 shows per card per session.
 */

class SRSQueue {
  /**
   * @param {Array} cards - Initial cards array from server
   * @param {Object} options - Configuration options
   */
  constructor(cards, options = {}) {
    this.cards = [...cards]; // Clone to avoid mutations
    this.currentIndex = 0;
    this.sessionAttempts = {}; // card_id → count
    this.studiedCards = new Set(); // Unique cards studied
    this.sessionKey = options.sessionKey || '';
    this.apiEndpoint = options.apiEndpoint || '/curriculum/api/v1/srs/grade';
    this.maxAttempts = options.maxAttempts || 3;
    this.onComplete = options.onComplete || null;
    this.onCardChange = options.onCardChange || null;
    this.onError = options.onError || null;

    // Initialize session attempts from server data
    for (const card of cards) {
      if (card.session_attempts) {
        this.sessionAttempts[card.card_id] = card.session_attempts;
      }
    }
  }

  /**
   * Get current card
   * @returns {Object|null}
   */
  getCurrentCard() {
    if (this.currentIndex >= this.cards.length) {
      return null;
    }
    return this.cards[this.currentIndex];
  }

  /**
   * Get progress info
   * @returns {Object}
   */
  getProgress() {
    return {
      current: this.currentIndex + 1,
      total: this.cards.length,
      studied: this.studiedCards.size,
      remaining: this.cards.length - this.currentIndex
    };
  }

  /**
   * Rate current card
   * @param {number} rating - 1, 2, or 3
   * @returns {Promise<Object>}
   */
  async rateCard(rating) {
    const card = this.getCurrentCard();
    if (!card) {
      return { success: false, error: 'No current card' };
    }

    const cardId = card.card_id;

    // Update local session attempts
    this.sessionAttempts[cardId] = (this.sessionAttempts[cardId] || 0) + 1;

    // Mark as studied
    this.studiedCards.add(cardId);

    // Send to server
    const result = await this._sendGrade(cardId, rating);

    if (!result.success) {
      if (this.onError) {
        this.onError(result.error);
      }
      return result;
    }

    // Check if we should requeue the card
    let requeued = false;
    if (result.requeue_position !== null && result.requeue_position !== undefined) {
      // Check session limit
      if (this.sessionAttempts[cardId] < this.maxAttempts) {
        this._requeueCard(card, result.requeue_position);
        requeued = true;
      }
    }

    // Move to next card
    this.currentIndex++;

    // Check if session complete
    if (this.currentIndex >= this.cards.length) {
      if (this.onComplete) {
        this.onComplete({
          studied: this.studiedCards.size,
          total: this.cards.length
        });
      }
      return {
        success: true,
        sessionComplete: true,
        studied: this.studiedCards.size
      };
    }

    // Notify card change
    if (this.onCardChange) {
      this.onCardChange(this.getCurrentCard(), this.getProgress());
    }

    return {
      success: true,
      requeued,
      nextCard: this.getCurrentCard(),
      progress: this.getProgress()
    };
  }

  /**
   * Requeue card at specified position
   * @private
   */
  _requeueCard(card, position) {
    // Calculate insert position (relative to current)
    const insertAt = Math.min(
      this.currentIndex + position + 1, // +1 because we'll increment currentIndex after
      this.cards.length
    );

    // Create requeue copy with flag
    const requeuedCard = {
      ...card,
      isRequeue: true,
      requeueNumber: this.sessionAttempts[card.card_id]
    };

    // Insert into queue
    this.cards.splice(insertAt, 0, requeuedCard);
  }

  /**
   * Send grade to server
   * @private
   */
  async _sendGrade(cardId, rating) {
    try {
      const response = await fetch(this.apiEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          card_id: cardId,
          rating: rating,
          session_key: this.sessionKey
        })
      });

      if (!response.ok) {
        const error = await response.json();
        return { success: false, error: error.error || 'Server error' };
      }

      return await response.json();
    } catch (error) {
      console.error('SRS grade error:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Skip current card (move to end without grading)
   */
  skipCard() {
    const card = this.getCurrentCard();
    if (!card) return null;

    // Move card to end
    this.cards.splice(this.currentIndex, 1);
    this.cards.push(card);

    // Notify change
    if (this.onCardChange) {
      this.onCardChange(this.getCurrentCard(), this.getProgress());
    }

    return this.getCurrentCard();
  }

  /**
   * Reset queue for new session
   */
  reset(newCards = null) {
    if (newCards) {
      this.cards = [...newCards];
    }
    this.currentIndex = 0;
    this.sessionAttempts = {};
    this.studiedCards.clear();
  }
}

/**
 * Utility: Get Russian pluralization for words
 * @param {number} count
 * @returns {string}
 */
function pluralizeWords(count) {
  const lastTwo = count % 100;
  const lastOne = count % 10;

  if (lastTwo >= 11 && lastTwo <= 19) {
    return 'слов';
  }
  if (lastOne === 1) {
    return 'слово';
  }
  if (lastOne >= 2 && lastOne <= 4) {
    return 'слова';
  }
  return 'слов';
}

/**
 * Utility: Format completion message
 * @param {number} studied
 * @returns {string}
 */
function formatCompletionMessage(studied) {
  return `Отлично! Сегодня вы изучили ${studied} ${pluralizeWords(studied)}`;
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { SRSQueue, pluralizeWords, formatCompletionMessage };
}
