// Interações leves: menu móvel, animação de entrada e contador do formulário.
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".nav-toggle");
  const menu = document.querySelector(".nav-menu");
  toggle?.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!open));
    menu?.classList.toggle("is-open", !open);
  });
  menu?.querySelectorAll("a").forEach(link => link.addEventListener("click", () => {
    menu.classList.remove("is-open"); toggle?.setAttribute("aria-expanded", "false");
  }));

  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add("is-visible"); observer.unobserve(entry.target); }
  }), { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(el => observer.observe(el));

  const textarea = document.querySelector("#experience");
  const counter = document.querySelector('[data-counter-for="experience"]');
  const updateCounter = () => { if (textarea && counter) counter.textContent = `${textarea.value.length}/1800`; };
  textarea?.addEventListener("input", updateCounter); updateCounter();

  document.querySelectorAll("[data-current-year]").forEach(el => el.textContent = new Date().getFullYear());
});
