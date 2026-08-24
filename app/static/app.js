const pantallaLogin = document.getElementById("pantalla-login");
const pantallaChat = document.getElementById("pantalla-chat");
const listaTecnicos = document.getElementById("lista-tecnicos");
const nombreActual = document.getElementById("nombre-actual");
const mensajesEl = document.getElementById("mensajes");
const formMensaje = document.getElementById("form-mensaje");
const inputTexto = document.getElementById("input-texto");
const btnCambiar = document.getElementById("btn-cambiar");
const accionesRapidas = document.getElementById("acciones-rapidas");

let tecnicoActual = localStorage.getItem("fieldti_tecnico") || null;

const CHIPS_DEFAULT = [
  { texto: "+ Nueva actividad", valor: "nueva actividad" },
  { texto: "⏸ Pausar", valor: "pausar" },
  { texto: "▶ Reanudar", valor: "reanudar" },
  { texto: "✓ Finalizar", valor: "finalizar" },
  { texto: "☰ Mis actividades", valor: "mis actividades" },
];

function renderizarChips(opciones = []) {
  accionesRapidas.innerHTML = "";
  if (opciones && opciones.length > 0) {
    opciones.forEach((op) => {
      const btn = document.createElement("button");
      btn.className = "chip chip-opcion";
      btn.dataset.texto = op;
      btn.textContent = op;
      accionesRapidas.appendChild(btn);
    });
    // Agregar chip de cancelar cuando hay opciones activas
    const btnCancel = document.createElement("button");
    btnCancel.className = "chip chip-cancelar";
    btnCancel.dataset.texto = "cancelar";
    btnCancel.textContent = "✕ Cancelar";
    accionesRapidas.appendChild(btnCancel);
  } else {
    CHIPS_DEFAULT.forEach((item) => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.dataset.texto = item.valor;
      btn.textContent = item.texto;
      accionesRapidas.appendChild(btn);
    });
  }
}

function agregarBurbuja(texto, tipo) {
  const div = document.createElement("div");
  div.className = `burbuja ${tipo}`;
  div.textContent = texto;
  mensajesEl.appendChild(div);
  mensajesEl.scrollTop = mensajesEl.scrollHeight;
  return div;
}

async function cargarTecnicos() {
  try {
    const res = await fetch("/api/tecnicos");
    const data = await res.json();
    listaTecnicos.innerHTML = "";
    (data.tecnicos || []).forEach((nombre) => {
      const btn = document.createElement("button");
      btn.className = "btn-tecnico";
      btn.textContent = nombre;
      btn.onclick = () => entrarComo(nombre);
      listaTecnicos.appendChild(btn);
    });
  } catch (err) {
    console.error("Error al cargar técnicos:", err);
  }
}

function entrarComo(nombre) {
  tecnicoActual = nombre;
  localStorage.setItem("fieldti_tecnico", nombre);
  nombreActual.textContent = nombre;
  pantallaLogin.classList.add("oculto");
  pantallaChat.classList.remove("oculto");
  mensajesEl.innerHTML = "";
  renderizarChips();
  agregarBurbuja(`Hola, ${nombre.split(" ")[0]}. Usa los botones de abajo o escribe libremente.`, "bot");
  inputTexto.focus();
}

async function mandarMensaje(texto) {
  if (!texto.trim()) return;
  agregarBurbuja(texto, "yo");
  const cargando = agregarBurbuja("…", "bot cargando");
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tecnico: tecnicoActual, texto }),
    });
    const data = await res.json();
    cargando.remove();
    (data.respuestas || []).forEach((r) => agregarBurbuja(r, "bot"));
    renderizarChips(data.opciones || []);
  } catch (err) {
    cargando.remove();
    agregarBurbuja("No pude conectar con el servidor. Revisa tu conexión e intenta de nuevo.", "bot");
  }
}

formMensaje.addEventListener("submit", (e) => {
  e.preventDefault();
  const texto = inputTexto.value;
  inputTexto.value = "";
  mandarMensaje(texto);
});

accionesRapidas.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  mandarMensaje(chip.dataset.texto);
});

btnCambiar.addEventListener("click", () => {
  localStorage.removeItem("fieldti_tecnico");
  tecnicoActual = null;
  pantallaChat.classList.add("oculto");
  pantallaLogin.classList.remove("oculto");
});

cargarTecnicos().then(() => {
  if (tecnicoActual) entrarComo(tecnicoActual);
});
