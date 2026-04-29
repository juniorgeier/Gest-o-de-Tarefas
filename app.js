const STATUS = ["Pendente", "Em andamento", "Concluído"];

const monthSelect = document.getElementById("monthSelect");
const newMonthButton = document.getElementById("newMonthButton");
const addTaskForm = document.getElementById("addTaskForm");
const taskDescriptionInput = document.getElementById("taskDescriptionInput");
const taskSectorInput = document.getElementById("taskSectorInput");
const taskNotesInput = document.getElementById("taskNotesInput");
const tasksContainer = document.getElementById("tasksContainer");
const taskTemplate = document.getElementById("taskTemplate");
const pendingCount = document.getElementById("pendingCount");
const inProgressCount = document.getElementById("inProgressCount");
const doneCount = document.getElementById("doneCount");

let months = [];
let activeMonth = "";

const monthLabel = new Intl.DateTimeFormat("pt-BR", {
  month: "long",
  year: "numeric"
});

function formatMonthKey(key) {
  const [year, month] = key.split("-").map(Number);
  return monthLabel.format(new Date(year, month - 1, 1));
}

async function apiGet(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Falha na API (${response.status})`);
  return response.json();
}

async function apiPost(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Falha na API (${response.status})`);
  }
  return response.json();
}

async function apiPatch(url, body) {
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "Erro ao atualizar");
  }
  return response.json();
}

async function apiDelete(url) {
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "Erro ao remover");
  }
  return response.json();
}

function renderMonthOptions() {
  monthSelect.innerHTML = "";
  for (const key of months) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = formatMonthKey(key);
    monthSelect.appendChild(option);
  }
  if (months.length > 0) {
    monthSelect.value = activeMonth;
  }
}

function renderSummary(tasks) {
  const summary = tasks.reduce(
    (acc, task) => {
      if (task.status === STATUS[0]) acc.pending += 1;
      if (task.status === STATUS[1]) acc.inProgress += 1;
      if (task.status === STATUS[2]) acc.done += 1;
      return acc;
    },
    { pending: 0, inProgress: 0, done: 0 }
  );
  pendingCount.textContent = String(summary.pending);
  inProgressCount.textContent = String(summary.inProgress);
  doneCount.textContent = String(summary.done);
}

function renderTasks(tasks) {
  tasksContainer.innerHTML = "";

  for (const task of tasks) {
    const node = taskTemplate.content.cloneNode(true);
    const title = node.querySelector(".task-title");
    const meta = node.querySelector(".task-meta");
    const statusSelect = node.querySelector(".status-select");
    const removeButton = node.querySelector(".remove-task-button");
    const notesInput = node.querySelector(".notes-input");
    const saveNotesButton = node.querySelector(".save-notes-button");

    title.textContent = `${task.id}. ${task.atividade}`;
    const notes = task.observacoes?.trim();
    meta.textContent = notes
      ? `Setor: ${task.setor || "Não informado"} | Observações: ${notes}`
      : `Setor: ${task.setor || "Não informado"}`;
    notesInput.value = task.observacoes || "";
    statusSelect.value = task.status;
    statusSelect.dataset.status = task.status;

    const saveNotes = async () => {
      const observacoes = notesInput.value.trim();
      try {
        await apiPatch("/api/tasks/notes", {
          month: activeMonth,
          taskId: task.id,
          observacoes
        });
        await loadAndRenderTasks(activeMonth);
      } catch (error) {
        alert(error.message);
      }
    };

    saveNotesButton.addEventListener("click", saveNotes);
    notesInput.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        await saveNotes();
      }
    });

    statusSelect.addEventListener("change", async (event) => {
      const value = event.target.value;
      event.target.dataset.status = value;
      try {
        await apiPatch("/api/tasks/status", {
          month: activeMonth,
          taskId: task.id,
          status: value
        });
        await loadAndRenderTasks(activeMonth);
      } catch (error) {
        alert(error.message);
      }
    });

    removeButton.addEventListener("click", async () => {
      const confirmed = window.confirm(
        `Confirma a exclusão da tarefa \"${task.atividade}\"?\n\nEssa ação remove a tarefa também dos próximos meses.`
      );
      if (!confirmed) return;

      try {
        await apiDelete(`/api/base-tasks/${task.id}`);
        await loadMonths();
        if (activeMonth) {
          await loadAndRenderTasks(activeMonth);
        }
      } catch (error) {
        alert(error.message);
      }
    });

    tasksContainer.appendChild(node);
  }

  renderSummary(tasks);
}

async function loadMonths() {
  const data = await apiGet("/api/months");
  months = data.months || [];

  if (!activeMonth) {
    const reference = data.referenceMonth;
    activeMonth = months.includes(reference) ? reference : (months[0] || "");
  }

  if (!months.includes(activeMonth) && months.length > 0) {
    activeMonth = months[0];
  }

  renderMonthOptions();
}

async function loadAndRenderTasks(month) {
  const data = await apiGet(`/api/tasks?month=${encodeURIComponent(month)}`);
  activeMonth = data.month;
  renderTasks(data.tasks || []);
}

async function init() {
  await loadMonths();
  if (activeMonth) {
    await loadAndRenderTasks(activeMonth);
  }

  monthSelect.addEventListener("change", async (event) => {
    activeMonth = event.target.value;
    await loadAndRenderTasks(activeMonth);
  });

  newMonthButton.addEventListener("click", async () => {
    await apiPost("/api/months/next");
    await loadMonths();
    activeMonth = months[0];
    monthSelect.value = activeMonth;
    await loadAndRenderTasks(activeMonth);
  });

  addTaskForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const atividade = taskDescriptionInput.value.trim();
    const setor = taskSectorInput.value.trim();
    const observacoes = taskNotesInput.value.trim();

    if (!atividade || !setor) {
      alert("Preencha descrição e setor.");
      return;
    }

    try {
      await apiPost("/api/base-tasks", { atividade, setor, observacoes });
      addTaskForm.reset();
      await loadMonths();
      if (activeMonth) {
        await loadAndRenderTasks(activeMonth);
      }
    } catch (error) {
      alert(error.message);
    }
  });
}

init().catch((error) => {
  console.error(error);
  tasksContainer.innerHTML = "<li>Erro ao iniciar o app. Verifique se o servidor está ativo.</li>";
});
