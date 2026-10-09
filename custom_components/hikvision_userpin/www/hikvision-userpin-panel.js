/**
 * Hikvision UserPin – native sidebar panel
 *
 * Embeds the two Lovelace cards (hikvision-userpin-users /
 * hikvision-userpin-events) in a plain HA panel. All data access happens
 * through the cards, i.e. via `hass.callApi` / `hass.callService` – every
 * request carries the signed-in user's auth token.
 */

const CARD_JS_URL = "/hikvision_userpin/hikvision-userpin-card.js";
const CARD_TAGS = ["hikvision-userpin-users", "hikvision-userpin-events"];
const WAIT_FOR_CARDS_MS = 3000;

class HikvisionUserPinPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._cards = [];
    this._built = false;
  }

  connectedCallback() {
    if (!this._built) {
      this._built = true;
      this._build();
    }
  }

  set hass(hass) {
    this._hass = hass;
    for (const card of this._cards) card.hass = hass;
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = Boolean(value);
    this._updateMenuButton();
  }

  get narrow() {
    return this._narrow;
  }

  set route(value) {
    this._route = value;
  }

  set panel(value) {
    this._panel = value;
  }

  async _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
        }
        .header {
          display: flex;
          align-items: center;
          gap: 8px;
          height: 56px;
          padding: 0 16px;
          box-sizing: border-box;
          background: var(--app-header-background-color, var(--primary-color));
          color: var(--app-header-text-color, #fff);
        }
        .header .title {
          font-size: 20px;
          font-weight: 400;
          line-height: 1;
        }
        .menu-button {
          display: none;
          background: none;
          border: none;
          color: inherit;
          cursor: pointer;
          padding: 8px;
          margin-left: -8px;
          line-height: 0;
        }
        :host([data-narrow]) .menu-button {
          display: inline-block;
        }
        .content {
          max-width: 1100px;
          margin: 0 auto;
          padding: 16px;
          box-sizing: border-box;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .loading {
          padding: 24px 16px;
          text-align: center;
          color: var(--secondary-text-color);
        }
      </style>
      <div class="header">
        <button class="menu-button" aria-label="Menü">
          <svg viewBox="0 0 24 24" width="24" height="24">
            <path fill="currentColor"
              d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"></path>
          </svg>
        </button>
        <div class="title">Hikvision UserPin</div>
      </div>
      <div class="content"><div class="loading">Lade…</div></div>
    `;

    this.shadowRoot
      .querySelector(".menu-button")
      .addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("hass-toggle-menu", {
            bubbles: true,
            composed: true,
          })
        );
      });

    this._updateMenuButton();

    try {
      await this._ensureCardsDefined();
    } catch (err) {
      this._showError(err);
      return;
    }

    this._mountCards();
  }

  _updateMenuButton() {
    if (!this.shadowRoot) return;
    if (this._narrow) {
      this.setAttribute("data-narrow", "");
    } else {
      this.removeAttribute("data-narrow");
    }
  }

  /**
   * The card JS is normally already loaded globally (add_extra_js_url).
   * Only import it when the elements are still undefined after a grace
   * period – importing unconditionally would make customElements.define
   * throw "already defined".
   */
  async _ensureCardsDefined() {
    const waiting = CARD_TAGS.map((tag) => customElements.whenDefined(tag));
    const allDefined = Promise.all(waiting).then(() => true);
    const timeout = new Promise((resolve) =>
      setTimeout(() => resolve(false), WAIT_FOR_CARDS_MS)
    );

    if (await Promise.race([allDefined, timeout])) return;

    if (CARD_TAGS.every((tag) => customElements.get(tag))) return;

    await import(CARD_JS_URL);
    await Promise.all(waiting);
  }

  _mountCards() {
    const content = this.shadowRoot.querySelector(".content");
    content.innerHTML = "";
    this._cards = [];

    for (const tag of CARD_TAGS) {
      const card = document.createElement(tag);
      if (typeof card.setConfig === "function") card.setConfig({});
      if (this._hass) card.hass = this._hass;
      content.appendChild(card);
      this._cards.push(card);
    }
  }

  _showError(err) {
    const content = this.shadowRoot.querySelector(".content");
    content.innerHTML = `<div class="loading">
      Die Hikvision-Cards konnten nicht geladen werden.
    </div>`;
    console.error("hikvision-userpin-panel: card load failed", err);
  }
}

customElements.define("hikvision-userpin-panel", HikvisionUserPinPanel);
