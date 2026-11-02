document.querySelectorAll("form[data-municipios-url]").forEach((form) => {
  const estado = form.querySelector("#id_estado");
  const municipio = form.querySelector("#id_municipio");
  const status = form.querySelector("#municipio-status");

  if (!estado || !municipio || !status) {
    return;
  }

  let requisicaoAtiva;
  const carregarMunicipios = async () => {
    requisicaoAtiva?.abort();
    const selecionado = municipio.value;
    if (!estado.value) {
      municipio.replaceChildren(new Option("Selecione primeiro um estado", ""));
      municipio.disabled = true;
      status.textContent = "";
      estado.removeAttribute("aria-busy");
      return;
    }

    const controlador = new AbortController();
    requisicaoAtiva = controlador;
    municipio.replaceChildren(new Option("Carregando municípios...", ""));
    municipio.disabled = true;
    status.textContent = "Carregando municípios...";
    estado.setAttribute("aria-busy", "true");

    try {
      const url = new URL(form.dataset.municipiosUrl, window.location.origin);
      url.searchParams.set("estado", estado.value);
      const resposta = await fetch(url, { signal: controlador.signal });
      const dados = await resposta.json();
      if (!resposta.ok) {
        throw new Error(dados.erro || "Não foi possível carregar os municípios.");
      }

      municipio.replaceChildren(new Option("Selecione um município", ""));
      dados.municipios.forEach((item) => {
        municipio.add(new Option(`${item.nome} (${item.codigo})`, item.codigo));
      });
      municipio.disabled = false;
      if (selecionado) {
        municipio.value = selecionado;
      }
      if (dados.municipios.length === 0) {
        status.textContent = "Não há municípios sincronizados para este estado.";
      } else {
        status.textContent = "Municípios carregados. Escolha um município.";
      }
    } catch (erro) {
      if (controlador.signal.aborted) {
        return;
      }
      municipio.replaceChildren(new Option("Municípios indisponíveis", ""));
      status.textContent = "Não foi possível carregar os municípios. Tente novamente.";
      console.error("Falha ao carregar municípios do estado selecionado.", erro);
    } finally {
      if (requisicaoAtiva === controlador) {
        estado.removeAttribute("aria-busy");
      }
    }
  };

  estado.addEventListener("change", carregarMunicipios);
  if (estado.value && municipio.options.length <= 1) {
    carregarMunicipios();
  }
});
