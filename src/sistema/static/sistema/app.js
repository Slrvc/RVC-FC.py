document.querySelectorAll("form[data-cidades-url]").forEach((form) => {
  const estado = form.querySelector("#id_estado");
  const cidade = form.querySelector("#id_cidade");
  const status = form.querySelector("#cidade-status");

  if (!estado || !cidade || !status) {
    return;
  }

  let requisicaoAtiva;
  estado.addEventListener("change", async () => {
    requisicaoAtiva?.abort();
    if (!estado.value) {
      cidade.replaceChildren(new Option("Selecione primeiro um estado", ""));
      cidade.disabled = true;
      status.textContent = "";
      estado.removeAttribute("aria-busy");
      return;
    }

    const controlador = new AbortController();
    requisicaoAtiva = controlador;
    cidade.replaceChildren(new Option("Carregando cidades...", ""));
    cidade.disabled = true;
    status.textContent = "Carregando cidades...";
    estado.setAttribute("aria-busy", "true");

    try {
      const url = new URL(form.dataset.cidadesUrl, window.location.origin);
      url.searchParams.set("estado", estado.value);
      const resposta = await fetch(url, { signal: controlador.signal });
      const dados = await resposta.json();
      if (!resposta.ok) {
        throw new Error(dados.erro || "Não foi possível carregar as cidades.");
      }

      cidade.replaceChildren(new Option("Selecione uma cidade", ""));
      dados.cidades.forEach((item) => {
        cidade.add(new Option(item.cidade, item.codigo));
      });
      cidade.disabled = false;
      if (dados.cidades.length === 0) {
        status.textContent = "Não há cidades cadastradas para este estado.";
      } else {
        status.textContent = "Cidades carregadas. Escolha um município.";
      }
    } catch (erro) {
      if (controlador.signal.aborted) {
        return;
      }
      cidade.replaceChildren(new Option("Cidades indisponíveis", ""));
      status.textContent = "Não foi possível carregar as cidades. Tente novamente.";
      console.error("Falha ao carregar cidades do estado selecionado.", erro);
    } finally {
      if (requisicaoAtiva === controlador) {
        estado.removeAttribute("aria-busy");
      }
    }
  });
});
