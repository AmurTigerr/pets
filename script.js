const state = {
  authenticated: false,
  user: null,
  questionnaire: null,
  looks: [],
  favorites: new Set(),
};

const body = document.body;
const pageType = body?.dataset.page;

if (pageType === "auth") {
  initAuthPage();
}

if (pageType === "forgot-password") {
  initForgotPasswordPage();
}

if (pageType === "reset-password") {
  initResetPasswordPage();
}

if (pageType === "reset-password-code") {
  initResetPasswordCodePage();
}

if (pageType === "cabinet") {
  initCabinetPage();
}

if (pageType === "questionnaire") {
  initQuestionnairePage();
}

if (pageType === "favorites") {
  initFavoritesPage();
}

initPolicyModal();

function initAuthPage() {
  const authMessage = document.querySelector("#auth-message");
  const loginForm = document.querySelector("#login-form");
  const registerForm = document.querySelector("#register-form");
  const authTabButtons = document.querySelectorAll("[data-auth-tab]");
  const authPanels = document.querySelectorAll(".auth-form-panel");

  authTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      authTabButtons.forEach((item) => item.classList.remove("active"));
      authPanels.forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      document.querySelector(`#${button.dataset.authTab}-form`)?.classList.add("active");
      showMessage(authMessage, "");
    });
  });

  loginForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    const result = await apiRequest("/api/login", {
      email: formData.get("email"),
      password: formData.get("password"),
    });

    if (!result.ok) {
      showMessage(authMessage, result.error, true);
      return;
    }

    window.location.href = "/cabinet";
  });

  registerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(registerForm);
    const password = formData.get("password");
    const passwordRepeat = formData.get("password_repeat");
    const privacyConsent = formData.get("privacy_consent");

    if (password !== passwordRepeat) {
      showMessage(authMessage, "Пароли не совпадают", true);
      return;
    }
    if (!privacyConsent) {
      showMessage(
        authMessage,
        "Нужно согласиться с политикой конфиденциальности и обработкой персональных данных.",
        true
      );
      return;
    }

    const result = await apiRequest("/api/register", {
      email: formData.get("email"),
      password,
      privacy_consent: true,
    });

    if (!result.ok) {
      showMessage(authMessage, result.error, true);
      return;
    }

    window.location.href = "/cabinet";
  });
}

function initPolicyModal() {
  const policyLinks = document.querySelectorAll("[data-open-policy]");
  if (!policyLinks.length) {
    return;
  }

  const modal = document.createElement("section");
  modal.className = "policy-modal hidden";
  modal.setAttribute("aria-hidden", "true");
  modal.innerHTML = `
    <div class="policy-modal__backdrop" data-policy-close></div>
    <div class="policy-modal__sheet" role="dialog" aria-modal="true" aria-label="Политика конфиденциальности">
      <button class="policy-modal__close" type="button" data-policy-close aria-label="Закрыть">×</button>
      <div class="policy-modal__content" id="policy-modal-content">
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const container = modal.querySelector("#policy-modal-content");
  if (container) {
    container.innerHTML = getPolicyMarkup();
  }

  policyLinks.forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      const href = link.getAttribute("href") || "/privacy-policy";
      const anchor = href.includes("#") ? href.split("#")[1] : "";
      await openPolicyModal(anchor);
    });
  });

  modal.querySelectorAll("[data-policy-close]").forEach((button) => {
    button.addEventListener("click", closePolicyModal);
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePolicyModal();
    }
  });

  async function openPolicyModal(anchor = "") {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    const target = anchor ? modal.querySelector(`#${CSS.escape(anchor)}`) : null;
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      modal.querySelector(".policy-modal__sheet")?.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function closePolicyModal() {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
  }
}

function initSiteFooter() {
  const shell = document.querySelector(".page-shell");
  if (!shell || shell.querySelector(".site-footer")) {
    return;
  }

  const footer = document.createElement("footer");
  footer.className = "site-footer";
  footer.innerHTML = `
    <div class="site-footer__grid">
      <div class="site-footer__block">
        <p class="site-footer__label">Дата</p>
        <p class="site-footer__value" data-footer-date></p>
      </div>
      <div class="site-footer__block">
        <p class="site-footer__label">Служба поддержки</p>
        <p class="site-footer__value">ElanTechStyle@yandex.ru</p>
        <p class="site-footer__label site-footer__label--spaced">Режим</p>
        <p class="site-footer__value">Ежедневно • 09:00–18:00 МСК</p>
      </div>
      <div class="site-footer__block">
        <p class="site-footer__label">Документы</p>
        <p class="site-footer__links">
          <a href="/privacy-policy" data-open-policy>Политика</a>
          <span>•</span>
          <span>Cookie</span>
        </p>
      </div>
    </div>
    <div class="site-footer__bottom">
      <span>ELAN TECH</span>
      <span>AI Ассистент по стилю</span>
    </div>
  `;

  shell.appendChild(footer);

  const dateNode = footer.querySelector("[data-footer-date]");
  if (dateNode) {
    const now = new Date();
    dateNode.textContent = now.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  }
}

function getPolicyMarkup() {
  return `
    <div class="policy-card policy-card--modal">
      <p class="policy-badge">Документ для сайта и формы регистрации</p>
      <h2>Политика конфиденциальности и обработки персональных данных</h2>
      <p class="policy-lead">
        Настоящая Политика определяет порядок обработки персональных данных
        пользователей сервиса ELAN TECH и меры по обеспечению их безопасности.
      </p>

      <div class="policy-meta">
        <span>Версия: 2026-08-20</span>
        <span>Журнал согласий: есть</span>
      </div>

      <div class="policy-section">
        <h3>1. Общие положения</h3>
        <p>
          Оператор персональных данных: <strong>ELAN TECH</strong>.
        </p>
        <p>
          Адрес: <strong>Некрасовский пер., 42, Таганрог, Ростовская обл., 347922</strong>.
        </p>
        <p>
          Контакты: <strong>elizaku@sfedu.ru</strong>.
        </p>
        <p class="policy-note">
          Сервис предоставляет функционал AI-ассистента по стилю. Доступ к функционалу предоставляется через личный кабинет.
        </p>
      </div>

      <div class="policy-section">
        <h3>2. Цели обработки персональных данных</h3>
        <ul class="policy-list">
          <li>Регистрация и авторизация пользователя по email и паролю.</li>
          <li>Обеспечение работы личного кабинета и функционала AI-ассистента.</li>
          <li>Персонализация рекомендаций и подбор образов по анкете.</li>
          <li>Техническая поддержка, восстановление доступа и защита аккаунта.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>3. Правовые основания обработки</h3>
        <ul class="policy-list">
          <li>Согласие пользователя на обработку персональных данных, выраженное при регистрации.</li>
          <li>Необходимость для исполнения договора и предоставления сервиса.</li>
          <li>Требования законодательства Российской Федерации.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>4. Категории и состав персональных данных</h3>
        <ul class="policy-list">
          <li>Email, используемый как логин для входа.</li>
          <li>Пароль, хранящийся только в хешированном виде.</li>
          <li>Данные анкеты: пол, рост, вес, обхват груди, талии и бёдер, цвет глаз, волос и кожи.</li>
          <li>Стилевые предпочтения, тип мероприятия, дополнительные пожелания, история выбранных образов.</li>
          <li>Технические данные: IP-адрес, тип устройства, браузер, время входов и журнал согласий.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>5. Порядок и условия обработки</h3>
        <p>
          Сбор данных происходит только с добровольного и однозначного согласия пользователя.
        </p>
        <p>
          При регистрации пользователь указывает email и задаёт собственный пароль, отдельно ставит чекбокс согласия с политикой, а факт согласия фиксируется в журнале.
        </p>
        <p>
          Данные хранятся только на серверах, физически расположенных в РФ. Передача данных третьим лицам допускается только при необходимости для работы сервиса и при наличии соответствующих оснований.
        </p>
        <p>
          Если используется иностранный сервис, это считается трансграничной передачей и требует отдельного согласия пользователя.
        </p>
        <p>
          Срок хранения данных - в течение срока действия аккаунта и далее в соответствии с законодательством. После отзыва согласия данные удаляются либо обезличиваются, если иное не требуется по закону.
        </p>
      </div>

      <div class="policy-section">
        <h3>6. Особенности обработки данных для входа</h3>
        <ul class="policy-list">
          <li>Email используется только как идентификатор (логин) в системе.</li>
          <li>Пароль не связан с почтовым ящиком пользователя и не хранится в открытом виде.</li>
          <li>Для восстановления доступа используется отдельный механизм без хранения паролей.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>7. Меры безопасности</h3>
        <ul class="policy-list">
          <li>Хранение паролей только в хешированном виде.</li>
          <li>Шифрование трафика и разграничение прав доступа к базе данных.</li>
          <li>Регулярное обновление программного обеспечения и средств защиты.</li>
          <li>Мониторинг инцидентов и реагирование на утечки.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>8. Права пользователя</h3>
        <ul class="policy-list">
          <li>Получить сведения об обработке своих данных.</li>
          <li>Запросить уточнение, блокирование или удаление данных.</li>
          <li>Отозвать согласие на обработку персональных данных.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>9. Файлы cookie и аналогичные технологии</h3>
        <ul class="policy-list">
          <li>При первом входе на сайт пользователь видит уведомление о cookie.</li>
          <li>Пользователь может принять все cookie, отклонить необязательные или настроить выбор.</li>
          <li>Выбор пользователя технически учитывается и сохраняется.</li>
          <li>Ссылка на Политику всегда доступна в футере сайта.</li>
        </ul>
      </div>

      <div class="policy-section">
        <h3>10. Уведомление Роскомнадзора</h3>
        <p>
          Оператор подал уведомление в Роскомнадзор о начале обработки персональных данных. В случае изменения целей, состава данных или подрядчиков уведомление актуализируется.
        </p>
      </div>

      <div class="policy-section">
        <h3>11. Заключительные положения</h3>
        <p>
          Актуальная версия Политики публикуется на странице сайта. Оператор вправе вносить изменения в Политику, а новая версия вступает в силу с даты публикации.
        </p>
      </div>
    </div>
  `;
}

function initForgotPasswordPage() {
  const messageEl = document.querySelector("#forgot-password-message");
  const linkEl = document.querySelector("#forgot-password-link");
  const form = document.querySelector("#forgot-password-form");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const result = await apiRequest("/api/password/forgot", {
      email: formData.get("email"),
    });

    if (!result.ok) {
      showMessage(messageEl, result.error, true);
      if (linkEl) {
        linkEl.classList.add("hidden");
        linkEl.innerHTML = "";
      }
      return;
    }

    showMessage(messageEl, result.data.message);
    if (linkEl) {
      linkEl.classList.remove("hidden");
      const localCode = result.data.recoveryCode
        ? `<br />Код для локальной проверки: <strong>${result.data.recoveryCode}</strong>`
        : "";
      const nextUrl = result.data.nextUrl || result.data.redirectUrl;
      linkEl.innerHTML = `Дальше откройте <a href="${nextUrl}" class="inline-link">${result.data.redirectUrl}</a> и введите код из письма.${localCode}`;
    }

    if (result.data.nextUrl || result.data.redirectUrl) {
      window.setTimeout(() => {
        window.location.href = result.data.nextUrl || result.data.redirectUrl;
      }, 1400);
    }
  });
}

function initResetPasswordPage() {
  const page = document.body;
  const token = page?.dataset.token || "";
  const tokenValid = page?.dataset.tokenValid === "true";
  const messageEl = document.querySelector("#reset-password-message");
  const form = document.querySelector("#reset-password-form");

  if (!tokenValid) {
    return;
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const password = formData.get("password");
    const passwordRepeat = formData.get("password_repeat");

    if (password !== passwordRepeat) {
      showMessage(messageEl, "Пароли не совпадают", true);
      return;
    }

    const result = await apiRequest("/api/password/reset", {
      token,
      password,
    });

    if (!result.ok) {
      showMessage(messageEl, result.error, true);
      return;
    }

    showMessage(messageEl, result.data.message);
    window.setTimeout(() => {
      window.location.href = "/auth";
    }, 1200);
  });
}

function initResetPasswordCodePage() {
  const messageEl = document.querySelector("#reset-password-code-message");
  const form = document.querySelector("#reset-password-code-form");
  const emailInput = form?.querySelector("input[name='email']");
  const emailFromUrl = new URLSearchParams(window.location.search).get("email") || "";

  if (emailInput && emailFromUrl) {
    emailInput.value = emailFromUrl;
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const password = formData.get("password");
    const passwordRepeat = formData.get("password_repeat");

    if (password !== passwordRepeat) {
      showMessage(messageEl, "Пароли не совпадают", true);
      return;
    }

    const result = await apiRequest("/api/password/reset-by-code", {
      email: formData.get("email"),
      code: formData.get("code"),
      password,
    });

    if (!result.ok) {
      showMessage(messageEl, result.error, true);
      return;
    }

    showMessage(messageEl, result.data.message);
    window.setTimeout(() => {
      window.location.href = "/auth";
    }, 1200);
  });
}

function initCabinetPage() {
  const accountEmail = document.querySelector("#account-email");
  const accountInitial = document.querySelector("#account-initial");
  const favoritesCount = document.querySelector("#favorites-count");
  const questionnaireProgress = document.querySelector("#questionnaire-progress");
  const questionnaireStatus = document.querySelector("#questionnaire-status");
  const favoritesPreview = document.querySelector("#cabinet-favorites-preview");
  const latestLookStrip = document.querySelector("#latest-look-strip");
  const latestLookMeta = document.querySelector("#latest-look-meta");
  const logoutButton = document.querySelector("#logout-button");

  logoutButton?.addEventListener("click", async () => {
    const result = await apiRequest("/api/logout", {}, "POST");
    if (!result.ok) {
      return;
    }
    window.location.href = "/auth";
  });

  bootstrap();

  async function bootstrap() {
    const result = await apiRequest("/api/session", null, "GET");
    if (!result.ok || !result.data.authenticated) {
      window.location.href = "/auth";
      return;
    }

    hydrateState(result.data);
    renderCabinet();
  }

  function hydrateState(payload) {
    state.authenticated = Boolean(payload.authenticated);
    state.user = payload.user || null;
    state.questionnaire = payload.questionnaire || null;
    state.looks = payload.looks || [];
    state.favorites = new Set(payload.favorites || []);
  }

  function renderCabinet() {
    const total = state.favorites.size;
    const email = state.user?.email || "Аккаунт не найден";
    const hasQuestionnaire = Boolean(state.questionnaire);
    const looks = Array.isArray(state.looks) ? state.looks : [];
    const favoriteLooks = looks.filter((look) => state.favorites.has(look.id));

    if (accountEmail) {
      accountEmail.textContent = email;
    }
    if (accountInitial) {
      accountInitial.textContent = email.trim().charAt(0).toUpperCase() || "E";
    }
    if (favoritesCount) {
      favoritesCount.textContent = `${total} ${declension(total, ["образ", "образа", "образов"])}`;
    }
    if (questionnaireProgress) {
      questionnaireProgress.textContent = hasQuestionnaire ? "12/12" : "0/12";
    }
    if (questionnaireStatus) {
      questionnaireStatus.textContent = hasQuestionnaire ? "Заполнена" : "Не заполнена";
      questionnaireStatus.classList.toggle("is-complete", hasQuestionnaire);
    }
    if (latestLookMeta) {
      latestLookMeta.textContent = looks.length
        ? `${looks.length} ${declension(looks.length, ["образ", "образа", "образов"])} · последняя генерация`
        : "Пока нет подборки";
    }
    renderCabinetFavorites(favoritesPreview, favoriteLooks);
    renderCabinetLatest(latestLookStrip, looks);
    logoutButton?.classList.remove("hidden");
  }
}

function renderCabinetFavorites(container, favoriteLooks) {
  if (!container) {
    return;
  }

  const cards = favoriteLooks.slice(0, 2).map((look) => renderMiniLook(look, "favorite-mini"));
  cards.push(`
    <a href="/favorites" class="favorite-add-card" aria-label="Открыть избранное">
      <span>+</span>
      <small>Отмечайте образы сердечком</small>
    </a>
  `);
  container.innerHTML = cards.join("");
}

function renderCabinetLatest(container, looks) {
  if (!container) {
    return;
  }

  if (!looks.length) {
    container.innerHTML = `
      <span class="latest-empty">Подборка появится после заполнения анкеты</span>
    `;
    return;
  }

  container.innerHTML = looks
    .slice(0, 7)
    .map((look) => renderMiniLook(look, "latest-mini"))
    .join("");
}

function renderMiniLook(look, className) {
  return `
    <a href="/looks/${look.id}" class="${className}" aria-label="Открыть образ ${escapeHtml(look.title)}">
      <img src="${look.image}" alt="${escapeHtml(look.title)}" />
      <span>${escapeHtml(look.title || "Образ")}</span>
    </a>
  `;
}

function initFavoritesPage() {
  const favoritesCount = document.querySelector("#favorites-count");
  const favoritesCounter = document.querySelector("#favorites-counter");
  const favoritesGrid = document.querySelector("#favorites-grid");
  const logoutButton = document.querySelector("#logout-button");

  logoutButton?.addEventListener("click", async () => {
    const result = await apiRequest("/api/logout", {}, "POST");
    if (!result.ok) {
      return;
    }
    window.location.href = "/auth";
  });

  bootstrap();

  async function bootstrap() {
    const result = await apiRequest("/api/session", null, "GET");
    if (!result.ok || !result.data.authenticated) {
      window.location.href = "/auth";
      return;
    }

    hydrateState(result.data);
    renderFavoritesPage();
  }

  function hydrateState(payload) {
    state.authenticated = Boolean(payload.authenticated);
    state.user = payload.user || null;
    state.questionnaire = payload.questionnaire || null;
    state.looks = payload.looks || [];
    state.favorites = new Set(payload.favorites || []);
  }

  function renderFavoritesPage() {
    const total = state.favorites.size;
    favoritesCount.textContent = `${total} ${declension(total, ["образ", "образа", "образов"])}`;
    favoritesCounter.textContent = `${total} ${declension(total, ["образ", "образа", "образов"])}`;
    logoutButton?.classList.remove("hidden");
    renderFavoriteCards(favoritesGrid);
  }
}

function initQuestionnairePage() {
  const styleMessage = document.querySelector("#style-message");
  const profileEmail = document.querySelector("#profile-email");
  const profileStatus = document.querySelector("#profile-status");
  const favoritesCount = document.querySelector("#favorites-count");
  const looksCounter = document.querySelector("#looks-counter");
  const favoritesCounter = document.querySelector("#favorites-counter");
  const looksGrid = document.querySelector("#looks-grid");
  const favoritesGrid = document.querySelector("#favorites-grid");
  const styleForm = document.querySelector("#style-form");
  const generateButton = styleForm?.querySelector("button[type='submit']");
  const logoutButton = document.querySelector("#logout-button");

  styleForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(styleForm);
    const payload = {
      gender: formData.get("gender"),
      limb_length: formData.get("limb_length"),
      cheekbones: formData.get("cheekbones"),
      height: formData.get("height"),
      weight: formData.get("weight"),
      age: formData.get("age"),
      bust: formData.get("bust"),
      waist: formData.get("waist"),
      hips: formData.get("hips"),
      body_shape: formData.get("body_shape"),
      lip_size: formData.get("lip_size"),
      hair_texture: formData.get("hair_texture"),
      eyes: formData.get("eyes"),
      hair: formData.get("hair"),
      skin: formData.get("skin"),
      event: formData.get("event"),
      preferred_colors: formData.get("preferred_colors"),
      extra_preferences: formData.get("extra_preferences"),
    };

    const validationError = validateStylePayload(payload);
    if (validationError) {
      showMessage(styleMessage, validationError, true);
      return;
    }

    state.questionnaire = payload;
    state.looks = [];
    state.favorites = new Set();
    renderAll();
    setLoadingState(true);
    showMessage(styleMessage, "Формирую 10 образов. Генерация может занять немного времени.");

    const result = await apiRequest("/api/questionnaire", payload);
    setLoadingState(false);

    if (!result.ok) {
      showMessage(styleMessage, result.error, true);
      return;
    }

    state.questionnaire = result.data.questionnaire;
    state.looks = result.data.looks;
    state.favorites = new Set(
      result.data.looks.filter((look) => look.isFavorite).map((look) => look.id)
    );
    await refreshGeneratedState();
    showMessage(styleMessage, result.data.message);
    renderAll();
    scrollToSection("#looks");
  });

  logoutButton?.addEventListener("click", async () => {
    const result = await apiRequest("/api/logout", {}, "POST");
    if (!result.ok) {
      showMessage(styleMessage, result.error, true);
      return;
    }
    window.location.href = "/auth";
  });

  bootstrap();

  async function bootstrap() {
    const result = await apiRequest("/api/session", null, "GET");
    if (!result.ok || !result.data.authenticated) {
      window.location.href = "/auth";
      return;
    }

    hydrateState(result.data);
    renderAll();
  }

  function hydrateState(payload) {
    state.authenticated = Boolean(payload.authenticated);
    state.user = payload.user || null;
    state.questionnaire = payload.questionnaire || null;
    state.looks = payload.looks || [];
    state.favorites = new Set(payload.favorites || []);
  }

  async function refreshGeneratedState() {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const result = await apiRequest("/api/session", null, "GET");
      if (result.ok && result.data.authenticated) {
        hydrateState(result.data);
        if (state.looks.length > 0) {
          return;
        }
      }
      await wait(500);
    }
  }

  function validateStylePayload(payload) {
    const limits = {
      height: [140, 220, "Рост должен быть от 140 до 220 см."],
      weight: [35, 220, "Вес должен быть от 35 до 220 кг."],
      age: [14, 100, "Возраст должен быть от 14 до 100 лет."],
      bust: [60, 150, "Обхват груди должен быть от 60 до 150 см."],
      waist: [45, 140, "Обхват талии должен быть от 45 до 140 см."],
      hips: [60, 160, "Обхват бёдер должен быть от 60 до 160 см."],
    };

    const values = {};
    for (const [field, [min, max, message]] of Object.entries(limits)) {
      const value = Number(String(payload[field] || "").replace(",", "."));
      if (!Number.isFinite(value)) {
        return "Введите числовые параметры анкеты без лишних символов.";
      }
      if (value < min || value > max) {
        return message;
      }
      values[field] = value;
    }

    const heightM = values.height / 100;
    const bmi = values.weight / (heightM * heightM);
    if (bmi < 14 || bmi > 55) {
      return "Проверьте рост и вес: сочетание выглядит нереалистично.";
    }

    if (values.bust > values.height * 0.78) {
      return "Проверьте обхват груди: значение слишком большое для указанного роста.";
    }

    if (values.waist > values.height * 0.72) {
      return "Проверьте обхват талии: значение слишком большое для указанного роста.";
    }

    if (values.hips > values.height * 0.86) {
      return "Проверьте обхват бёдер: значение слишком большое для указанного роста.";
    }

    if (Math.max(values.bust, values.waist, values.hips) > values.weight * 2.15 + 10) {
      return "Проверьте вес и обхваты: сочетание выглядит нереалистично.";
    }

    if (Math.abs(values.bust - values.hips) > 45) {
      return "Проверьте обхваты груди и бёдер: разница выглядит нереалистично.";
    }

    if (values.waist > Math.max(values.bust, values.hips) + 20) {
      return "Проверьте обхват талии: значение слишком сильно выбивается из пропорций.";
    }

    if (values.waist < Math.min(values.bust, values.hips) - 55) {
      return "Проверьте обхват талии: разница с грудью и бёдрами выглядит нереалистично.";
    }

    const preferredColors = String(payload.preferred_colors || "").trim();
    if (preferredColors.length < 2 || preferredColors.length > 120) {
      return "Укажите предпочтительные цвета текстом до 120 символов.";
    }

    const event = String(payload.event || "").trim();
    if (event.length < 2 || event.length > 160) {
      return "Опишите тип мероприятия текстом до 160 символов.";
    }

    const extraPreferences = String(payload.extra_preferences || "").trim();
    if (extraPreferences.length > 600) {
      return "Дополнительные предпочтения должны быть короче 600 символов.";
    }

    return "";
  }

  function renderAll() {
    renderSummary();
    fillQuestionnaire();
    renderLooks();
    renderFavoriteCards(favoritesGrid);
    logoutButton?.classList.remove("hidden");
  }

  function renderSummary() {
    const total = state.favorites.size;
    if (profileEmail) {
      profileEmail.textContent = state.user?.email || "Пользователь";
    }
    if (profileStatus) {
      profileStatus.textContent = buildStatusLabel();
    }
    if (favoritesCount) {
      favoritesCount.textContent = `${total} ${declension(total, ["образ", "образа", "образов"])}`;
    }
    if (looksCounter) {
      looksCounter.textContent = `${total} в избранном`;
    }
    if (favoritesCounter) {
      favoritesCounter.textContent = `${total} ${declension(total, ["образ", "образа", "образов"])}`;
    }
  }

  function buildStatusLabel() {
    if (!state.questionnaire) {
      return "Заполните анкету на этой странице для первого персонального подбора.";
    }
    if (state.favorites.size > 0) {
      return "Анкета сохранена, а избранные образы доступны и здесь, и в кабинете.";
    }
    return "Анкета сохранена. Выберите лучшие варианты и добавьте их в избранное.";
  }

  function fillQuestionnaire() {
    if (!styleForm || !state.questionnaire) {
      if (!state.questionnaire) {
        styleForm?.reset();
      }
      return;
    }

    setFieldValue("gender", state.questionnaire.gender || "");
    setFieldValue("limb_length", state.questionnaire.limb_length || "");
    setFieldValue("cheekbones", state.questionnaire.cheekbones || "");
    setFieldValue("height", state.questionnaire.height || "");
    setFieldValue("weight", state.questionnaire.weight || "");
    setFieldValue("age", state.questionnaire.age || "");
    setFieldValue("bust", state.questionnaire.bust || "");
    setFieldValue("waist", state.questionnaire.waist || "");
    setFieldValue("hips", state.questionnaire.hips || "");
    setFieldValue("body_shape", state.questionnaire.body_shape || "");
    setFieldValue("lip_size", state.questionnaire.lip_size || "");
    setFieldValue("hair_texture", state.questionnaire.hair_texture || "");
    setFieldValue("eyes", state.questionnaire.eyes || "");
    setFieldValue("hair", state.questionnaire.hair || "");
    setFieldValue("skin", state.questionnaire.skin || "");
    setFieldValue("event", state.questionnaire.event || "");
    setFieldValue("preferred_colors", state.questionnaire.preferred_colors || "");
    setFieldValue("extra_preferences", state.questionnaire.extra_preferences || "");
  }

  function setFieldValue(name, value) {
    const field = styleForm?.elements.namedItem(name);
    if (field) {
      field.value = value;
    }
  }

  function renderLooks() {
    if (!looksGrid) {
      return;
    }

    if (!state.looks.length) {
      looksGrid.innerHTML = "";
      return;
    }

    looksGrid.innerHTML = state.looks
      .map(
        (look) => `
          <article class="look-card interactive catalog ${look.isFavorite ? "selected" : ""}" data-look-id="${look.id}">
            <a href="/looks/${look.id}" class="look-card-link" aria-label="Открыть образ ${look.title}">
              <div class="look-photo-frame catalog">
                <img src="${look.image}" alt="${look.title}" class="look-photo" style="object-position: ${look.imagePosition};" />
              </div>
            </a>
            <div class="look-meta">
              <div class="look-card-top compact">
                <div class="look-tags">
                  ${renderLookTags(look)}
                </div>
                <button class="save-button" type="button" aria-pressed="${look.isFavorite}" data-action="favorite">
                  ${look.isFavorite ? "В избранном" : "В избранное"}
                </button>
              </div>
              <a href="/looks/${look.id}" class="look-name look-name-link">${look.title}</a>
              <p class="look-caption">${look.note || look.vibe}</p>
            </div>
          </article>
        `
      )
      .join("");

    looksGrid.querySelectorAll("[data-action='favorite']").forEach((button) => {
      button.addEventListener("click", async () => {
        const card = button.closest("[data-look-id]");
        const lookId = card?.dataset.lookId;
        if (!lookId) {
          return;
        }
        await toggleFavorite(lookId);
      });
    });
  }

  async function toggleFavorite(lookId) {
    const favorite = !state.favorites.has(lookId);
    const result = await apiRequest("/api/favorites", { look_id: lookId, favorite });
    if (!result.ok) {
      showMessage(styleMessage, result.error, true);
      return;
    }

    if (favorite) {
      state.favorites.add(lookId);
    } else {
      state.favorites.delete(lookId);
    }

    state.looks = state.looks.map((look) =>
      look.id === lookId ? { ...look, isFavorite: favorite } : look
    );
    renderAll();
  }

  function setLoadingState(isLoading) {
    if (!generateButton) {
      return;
    }

    generateButton.disabled = isLoading;
    generateButton.textContent = isLoading ? "Формируем 10 образов..." : "Получить 10 образов";
  }
}

function renderFavoriteCards(container) {
  if (!container) {
    return;
  }

  const favoriteLooks = state.looks.filter((look) => state.favorites.has(look.id));
  if (!favoriteLooks.length) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = favoriteLooks
    .map(
      (look) => `
        <article class="look-card catalog favorite-card">
          <a href="/looks/${look.id}" class="look-card-link" aria-label="Открыть образ ${look.title}">
            <div class="look-photo-frame catalog">
              <img src="${look.image}" alt="${look.title}" class="look-photo" style="object-position: ${look.imagePosition};" />
            </div>
          </a>
          <div class="look-meta">
            <div class="look-tags">
              ${renderLookTags(look)}
            </div>
            <a href="/looks/${look.id}" class="look-name look-name-link">${look.title}</a>
            <p class="look-caption">${look.note || look.vibe}</p>
          </div>
        </article>
      `
    )
    .join("");
}

function renderLookTags(look) {
  const tags = Array.isArray(look.tags) && look.tags.length
    ? look.tags
    : String(look.meta || look.vibe || "Кибби").split("•");

  return tags
    .map((tag) => String(tag).trim())
    .filter(Boolean)
    .slice(0, 2)
    .map((tag) => `<span class="look-tag">${tag}</span>`)
    .join("");
}

async function apiRequest(url, payload = {}, method = "POST") {
  try {
    const options = {
      method,
      headers: {
        "Content-Type": "application/json",
      },
    };

    if (method !== "GET") {
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(url, options);
    const data = await response.json();

    if (!response.ok) {
      return { ok: false, error: data.error || "Не удалось выполнить запрос." };
    }

    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: "Сервер недоступен. Проверьте, что приложение запущено." };
  }
}

function showMessage(element, text, isError = false) {
  if (!element) {
    return;
  }

  element.textContent = text;
  element.classList.toggle("error", isError);
}

function scrollToSection(selector) {
  document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function declension(value, forms) {
  const mod10 = value % 10;
  const mod100 = value % 100;

  if (mod10 === 1 && mod100 !== 11) {
    return forms[0];
  }

  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return forms[1];
  }

  return forms[2];
}
