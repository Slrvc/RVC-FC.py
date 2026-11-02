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

document.querySelectorAll("form").forEach((form) => {
  const tipo = form.querySelector("#id_tipo_usuario");
  const empresa = form.querySelector("#id_empresa");
  const upcs = form.querySelector("#id_upcs");
  if (!tipo || !empresa || !upcs) {
    return;
  }

  const blocoDe = (campo) => campo.closest(".field") || campo.parentElement;
  const atualizar = () => {
    const gestor = tipo.value !== "admin";
    blocoDe(empresa).hidden = !gestor;
    blocoDe(upcs).hidden = !gestor;
    const secao = blocoDe(empresa).closest("fieldset, section");
    if (secao && secao.contains(blocoDe(upcs))) {
      secao.hidden = !gestor;
    }
    Array.from(upcs.options).forEach((opcao) => {
      const visivel = !empresa.value || opcao.dataset.empresa === empresa.value;
      opcao.hidden = !visivel;
      if (!visivel) {
        opcao.selected = false;
      }
    });
  };

  tipo.addEventListener("change", atualizar);
  empresa.addEventListener("change", atualizar);
  atualizar();
});

const soDigitos = (valor) => valor.replace(/\D/g, "");
const mascaras = {
  cnpj: (d) =>
    d
      .slice(0, 14)
      .replace(/^(\d{2})(\d)/, "$1.$2")
      .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
      .replace(/\.(\d{3})(\d)/, ".$1/$2")
      .replace(/(\d{4})(\d)/, "$1-$2"),
  cpf: (d) =>
    d
      .slice(0, 11)
      .replace(/(\d{3})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d)/, "$1.$2")
      .replace(/(\d{3})(\d{1,2})$/, "$1-$2"),
  cep: (d) => d.slice(0, 8).replace(/^(\d{5})(\d)/, "$1-$2"),
  telefone: (d) => {
    const n = d.slice(0, 11);
    if (n.length <= 2) {
      return n ? `(${n}` : "";
    }
    const miolo = n.length > 10 ? 7 : 6;
    const resto = n.slice(2);
    return resto.length > miolo - 2
      ? `(${n.slice(0, 2)}) ${resto.slice(0, miolo - 2)}-${resto.slice(miolo - 2)}`
      : `(${n.slice(0, 2)}) ${resto}`;
  },
};

document.querySelectorAll("input[data-mask]").forEach((campo) => {
  const tipo = campo.dataset.mask;
  const aplicar = () => {
    const d = soDigitos(campo.value);
    const formatar =
      tipo === "cpf_cnpj" ? (d.length > 11 ? mascaras.cnpj : mascaras.cpf) : mascaras[tipo];
    campo.value = formatar(d);
  };
  campo.addEventListener("input", aplicar);
  aplicar();
});
