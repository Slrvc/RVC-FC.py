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

document.querySelectorAll("form[data-plantios-url]").forEach((form) => {
  const fazenda = form.querySelector("#id_fazenda");
  const plantio = form.querySelector("#id_plantio");
  const status = form.querySelector("#plantio-status");

  if (!fazenda || !plantio || !status) {
    return;
  }

  let requisicaoAtiva;
  const carregarPlantios = async (preservarSelecionado = false) => {
    requisicaoAtiva?.abort();
    const selecionado = preservarSelecionado ? plantio.value : "";
    if (!fazenda.value) {
      plantio.replaceChildren(new Option("Selecione primeiro uma fazenda", ""));
      plantio.disabled = true;
      status.textContent = "";
      fazenda.removeAttribute("aria-busy");
      return;
    }

    const controlador = new AbortController();
    requisicaoAtiva = controlador;
    plantio.replaceChildren(new Option("Carregando plantios...", ""));
    plantio.disabled = true;
    status.textContent = "Carregando plantios...";
    fazenda.setAttribute("aria-busy", "true");

    try {
      const url = new URL(form.dataset.plantiosUrl, window.location.origin);
      url.searchParams.set("fazenda", fazenda.value);
      const resposta = await fetch(url, { signal: controlador.signal });
      const dados = await resposta.json();
      if (!resposta.ok) {
        throw new Error(dados.erro || "Não foi possível carregar os plantios.");
      }

      plantio.replaceChildren(new Option("Sem plantio vinculado", ""));
      dados.plantios.forEach((item) => {
        plantio.add(new Option(item.nome, item.codigo));
      });
      plantio.disabled = false;
      if (selecionado) {
        plantio.value = selecionado;
      }
      status.textContent =
        dados.plantios.length === 0
          ? "Não há plantios cadastrados para esta fazenda."
          : "Plantios carregados para a fazenda selecionada.";
    } catch (erro) {
      if (controlador.signal.aborted) {
        return;
      }
      plantio.replaceChildren(new Option("Plantios indisponíveis", ""));
      status.textContent = "Não foi possível carregar os plantios. Tente novamente.";
      console.error("Falha ao carregar plantios da fazenda selecionada.", erro);
    } finally {
      if (requisicaoAtiva === controlador) {
        fazenda.removeAttribute("aria-busy");
      }
    }
  };

  fazenda.addEventListener("change", () => {
    const preservar = fazenda.dataset.preservarPlantio === "true";
    delete fazenda.dataset.preservarPlantio;
    carregarPlantios(preservar);
  });
  if (fazenda.value) {
    carregarPlantios(true);
  } else {
    plantio.replaceChildren(new Option("Selecione primeiro uma fazenda", ""));
    plantio.disabled = true;
  }
});

document.querySelectorAll("form[data-talhoes-url]").forEach((form) => {
  const inventario = form.querySelector("#id_inventario");
  const talhao = form.querySelector("#id_talhao");
  const area = form.querySelector("#id_area_ha");
  const volume = form.querySelector("#id_volume_total");
  const saldo = form.querySelector("#id_saldo_a_retirar_m3");
  const arvores = form.querySelector("#id_numero_arvores");
  const status = form.querySelector("#talhao-status");

  if (!inventario || !talhao || !area || !volume || !saldo || !arvores || !status) {
    return;
  }

  let requisicaoAtiva;
  const carregarTalhoes = async (preservarSelecionado = false) => {
    requisicaoAtiva?.abort();
    const selecionado = preservarSelecionado ? talhao.value : "";
    if (!inventario.value) {
      talhao.replaceChildren(new Option("Selecione primeiro um inventário", ""));
      talhao.disabled = true;
      status.textContent = "";
      inventario.removeAttribute("aria-busy");
      return;
    }

    const controlador = new AbortController();
    requisicaoAtiva = controlador;
    talhao.replaceChildren(new Option("Carregando talhões...", ""));
    talhao.disabled = true;
    status.textContent = "Carregando talhões...";
    inventario.setAttribute("aria-busy", "true");

    try {
      const url = new URL(form.dataset.talhoesUrl, window.location.origin);
      url.searchParams.set("inventario", inventario.value);
      const resposta = await fetch(url, { signal: controlador.signal });
      const dados = await resposta.json();
      if (!resposta.ok) {
        throw new Error(dados.erro || "Não foi possível carregar os talhões.");
      }

      talhao.replaceChildren(new Option("Selecione um talhão", ""));
      dados.talhoes.forEach((item) => {
        const opcao = new Option(item.identificacao, item.codigo);
        opcao.dataset.area = item.area_ha;
        opcao.dataset.volume = item.volume_total;
        opcao.dataset.saldo = item.saldo_a_retirar_m3;
        opcao.dataset.arvores = item.numero_arvores;
        talhao.add(opcao);
      });
      talhao.disabled = false;
      if (selecionado) {
        talhao.value = selecionado;
      }
      status.textContent =
        dados.talhoes.length === 0
          ? "Não há talhões cadastrados para a fazenda deste inventário."
          : "Talhões carregados para a fazenda do inventário.";
    } catch (erro) {
      if (controlador.signal.aborted) {
        return;
      }
      talhao.replaceChildren(new Option("Talhões indisponíveis", ""));
      status.textContent = "Não foi possível carregar os talhões. Tente novamente.";
      console.error("Falha ao carregar talhões do inventário selecionado.", erro);
    } finally {
      if (requisicaoAtiva === controlador) {
        inventario.removeAttribute("aria-busy");
      }
    }
  };

  inventario.addEventListener("change", () => {
    area.value = "";
    volume.value = "";
    saldo.value = "";
    arvores.value = "";
    carregarTalhoes();
  });
  talhao.addEventListener("change", () => {
    const opcao = talhao.selectedOptions[0];
    if (!opcao || !opcao.value) {
      area.value = "";
      volume.value = "";
      saldo.value = "";
      arvores.value = "";
      return;
    }
    area.value = opcao.dataset.area;
    volume.value = opcao.dataset.volume;
    saldo.value = opcao.dataset.saldo;
    arvores.value = opcao.dataset.arvores;
  });

  if (inventario.value) {
    carregarTalhoes(true);
  } else {
    talhao.replaceChildren(new Option("Selecione primeiro um inventário", ""));
    talhao.disabled = true;
  }
});

document.querySelectorAll("form[data-colheita-talhoes-url]").forEach((form) => {
  const campo = (nome) => form.querySelector(`#id_${nome}`);
  const inventario = campo("inventario");
  const talhao = campo("talhao");
  const etapa = campo("etapa");
  const area = campo("area_ha");
  const volume = campo("volume_m3");
  const execucao = campo("tipo_execucao");
  const fornecedor = campo("fornecedor");
  const unidade = campo("unidade_pagamento");
  const valor = campo("valor_unitario");
  const resumo = form.querySelector("#colheita-talhao-resumo");
  const total = form.querySelector("#colheita-valor-total");
  const elementos = [inventario, talhao, etapa, area, volume, execucao, fornecedor];
  if (elementos.includes(null) || !unidade || !valor || !resumo || !total) {
    return;
  }

  const fatorMst = Number.parseFloat(form.dataset.fatorMst) || 1.5;
  const numero = (texto) => {
    const valorNumerico = Number.parseFloat(String(texto || "").replace(",", "."));
    return Number.isFinite(valorNumerico) ? valorNumerico : null;
  };
  const formatar = (valorNumerico, casas = 2) =>
    valorNumerico.toLocaleString("pt-BR", {
      minimumFractionDigits: casas,
      maximumFractionDigits: casas,
    });
  // Área e valor seguem os cálculos enquanto o usuário não digitar outro.
  let areaAutomatica = area.value === "";
  let valorAutomatico = valor.value === "";
  area.addEventListener("input", () => {
    areaAutomatica = area.value === "";
    atualizar();
  });
  valor.addEventListener("input", () => {
    valorAutomatico = valor.value === "";
    atualizar();
  });

  const atualizar = () => {
    const opcao = talhao.selectedOptions[0];
    const volumeInformado = numero(volume.value);
    resumo.classList.remove("field-status-erro");
    if (!opcao || !opcao.value || opcao.dataset.area === undefined) {
      resumo.textContent = "";
    } else {
      const volumeTalhao = numero(opcao.dataset.volume);
      const feito = numero(opcao.dataset.feito) || 0;
      const rendimento = numero(opcao.dataset.rendimento);
      const partes = [];
      if (volumeTalhao !== null) {
        const aFazer = volumeTalhao - feito;
        partes.push(
          `Inventário ${formatar(volumeTalhao)} m³`,
          `já feito nesta etapa ${formatar(feito)} m³`,
          `a fazer ${formatar(aFazer)} m³`,
        );
        if (volumeInformado !== null) {
          const restante = aFazer - volumeInformado;
          partes.push(`restará ${formatar(restante)} m³`);
          if (restante < -0.005) {
            resumo.classList.add("field-status-erro");
          }
        }
      }
      partes.push(
        rendimento === null
          ? "sem rendimento (m³/ha) no inventário ou no talhão"
          : `rendimento ${formatar(rendimento, 3)} m³/ha`,
      );
      resumo.textContent = partes.join(" · ");
      if (areaAutomatica) {
        area.value =
          rendimento && volumeInformado !== null
            ? (volumeInformado / rendimento).toFixed(4)
            : "";
      }
    }
    const areaInformada = numero(area.value);
    const quantidade =
      unidade.value === "HA"
        ? areaInformada
        : unidade.value === "MST" && volumeInformado !== null
          ? volumeInformado * fatorMst
          : volumeInformado;
    const valorUnitario = numero(valor.value);
    total.textContent =
      quantidade !== null && valorUnitario !== null
        ? `Valor a pagar: R$ ${formatar(quantidade * valorUnitario)}`
        : "";
  };

  let requisicaoTarifa;
  const buscarTarifa = async () => {
    if (!valorAutomatico) {
      return;
    }
    requisicaoTarifa?.abort();
    if (execucao.value !== "TERCEIRIZADA" || !fornecedor.value) {
      valor.value = "";
      atualizar();
      return;
    }
    const controlador = new AbortController();
    requisicaoTarifa = controlador;
    try {
      const url = new URL(form.dataset.tarifaUrl, window.location.origin);
      url.searchParams.set("fornecedor", fornecedor.value);
      url.searchParams.set("servico", etapa.value);
      const data = campo("data_inicio")?.value;
      if (data) {
        url.searchParams.set("data", data);
      }
      const resposta = await fetch(url, { signal: controlador.signal });
      const { tarifa } = await resposta.json();
      if (tarifa && ["M3", "MST", "HA"].includes(tarifa.unidade)) {
        valor.value = tarifa.valor;
        unidade.value = tarifa.unidade;
      } else {
        valor.value = "";
      }
      atualizar();
    } catch (erro) {
      if (!controlador.signal.aborted) {
        console.error("Falha ao buscar a tarifa do empreiteiro.", erro);
      }
    }
  };

  let requisicaoTalhoes;
  const carregarTalhoes = async () => {
    requisicaoTalhoes?.abort();
    if (!inventario.value) {
      atualizar();
      return;
    }
    const selecionado = talhao.value;
    const controlador = new AbortController();
    requisicaoTalhoes = controlador;
    resumo.textContent = "Carregando talhões do inventário...";
    try {
      const url = new URL(form.dataset.colheitaTalhoesUrl, window.location.origin);
      url.searchParams.set("inventario", inventario.value);
      url.searchParams.set("etapa", etapa.value);
      if (form.dataset.colheita) {
        url.searchParams.set("colheita", form.dataset.colheita);
      }
      const resposta = await fetch(url, { signal: controlador.signal });
      const dados = await resposta.json();
      if (!resposta.ok) {
        throw new Error(dados.erro || "Não foi possível carregar os talhões.");
      }
      talhao.replaceChildren(new Option("Selecione um talhão", ""));
      dados.talhoes.forEach((item) => {
        const opcao = new Option(item.identificacao, item.codigo);
        opcao.dataset.area = item.area_ha;
        opcao.dataset.volume = item.volume_talhao_m3;
        opcao.dataset.feito = item.volume_feito_m3;
        opcao.dataset.rendimento = item.rendimento_m3_ha;
        talhao.add(opcao);
      });
      talhao.value = selecionado;
      atualizar();
    } catch (erro) {
      if (controlador.signal.aborted) {
        return;
      }
      resumo.textContent = "Não foi possível carregar os dados do talhão.";
      console.error("Falha ao carregar talhões da colheita.", erro);
    }
  };

  inventario.addEventListener("change", carregarTalhoes);
  etapa.addEventListener("change", () => {
    carregarTalhoes();
    buscarTarifa();
  });
  talhao.addEventListener("change", atualizar);
  volume.addEventListener("input", atualizar);
  unidade.addEventListener("change", atualizar);
  [execucao, fornecedor, campo("data_inicio")].forEach((item) =>
    item?.addEventListener("change", buscarTarifa),
  );
  carregarTalhoes();
});

document.querySelectorAll("form").forEach((form) => {
  const modalidade = form.querySelector("#id_modalidade");
  const upcs = form.querySelector("#id_upcs");
  if (!modalidade || !upcs) {
    return;
  }

  const atualizarSelecaoUpcs = () => {
    const permiteMultiplas = modalidade.value === "NOTA_FISCAL";
    if (upcs.multiple === permiteMultiplas) {
      return;
    }
    if (!permiteMultiplas) {
      const selecionadas = Array.from(upcs.selectedOptions);
      selecionadas.slice(1).forEach((opcao) => {
        opcao.selected = false;
      });
    }
    upcs.multiple = permiteMultiplas;
  };

  modalidade.addEventListener("change", atualizarSelecaoUpcs);
  atualizarSelecaoUpcs();
});

document.querySelectorAll("form").forEach((form) => {
  const tipo = form.querySelector("#id_tipo_usuario");
  const empresas = form.querySelector("#id_empresas");
  const upcs = form.querySelector("#id_upcs");
  if (!tipo || !empresas || !upcs) {
    return;
  }

  const blocoDe = (campo) => campo.closest(".field") || campo.parentElement;
  const atualizar = () => {
    const gestor = tipo.value !== "admin";
    blocoDe(empresas).hidden = !gestor;
    blocoDe(upcs).hidden = !gestor;
    const secao = blocoDe(empresas).closest("fieldset, section");
    if (secao && secao.contains(blocoDe(upcs))) {
      secao.hidden = !gestor;
    }
    const marcadas = Array.from(empresas.selectedOptions, (opcao) => opcao.value);
    Array.from(upcs.options).forEach((opcao) => {
      const visivel =
        marcadas.length === 0 || marcadas.includes(opcao.dataset.empresa);
      opcao.hidden = !visivel;
      if (!visivel) {
        opcao.selected = false;
      }
    });
  };

  tipo.addEventListener("change", atualizar);
  empresas.addEventListener("change", atualizar);
  atualizar();
});

document.querySelectorAll("form").forEach((form) => {
  const tipo = form.querySelector("#id_tipo");
  const matriz = form.querySelector("#id_matriz");
  if (!tipo || !matriz) {
    return;
  }

  // Matriz não tem matriz nem descrição de filial: os campos só aparecem na filial.
  const campos = [matriz, form.querySelector("#id_descricao_filial")]
    .filter(Boolean)
    .map((campo) => campo.closest(".field") || campo.parentElement);
  const atualizar = () => {
    const filial = tipo.value === "FILIAL";
    campos.forEach((bloco) => {
      bloco.hidden = !filial;
    });
  };

  tipo.addEventListener("change", atualizar);
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

document.querySelectorAll("form").forEach((form) => {
  const volume = form.querySelector("#id_volume_total");
  const arvores = form.querySelector("#id_numero_arvores");
  const vmi = form.querySelector("#id_vmi");
  if (!volume || !arvores || !vmi) {
    return;
  }

  const atualizarVmi = () => {
    const volumeTotal = Number(volume.value.replace(",", "."));
    const numeroArvores = Number(arvores.value.replace(",", "."));
    vmi.value = "";
    if (
      volume.value &&
      arvores.value &&
      Number.isFinite(volumeTotal) &&
      Number.isFinite(numeroArvores) &&
      numeroArvores > 0
    ) {
      vmi.value = (volumeTotal / numeroArvores).toFixed(4);
    }
  };
  volume.addEventListener("input", atualizarVmi);
  arvores.addEventListener("input", atualizarVmi);
  atualizarVmi();
});

document.querySelectorAll("form").forEach((form) => {
  const volume = form.querySelector("#id_volume_m3[data-volume-retirado]");
  const saldo = form.querySelector("#id_saldo_a_retirar_m3");
  if (!volume || !saldo) {
    return;
  }

  const volumeRetirado = Number(volume.dataset.volumeRetirado);
  const atualizarSaldo = () => {
    if (!volume.value) {
      saldo.value = "";
      return;
    }
    const volumeTotal = Number(volume.value);
    if (Number.isFinite(volumeTotal)) {
      saldo.value = (volumeTotal - volumeRetirado).toFixed(3);
    }
  };
  volume.addEventListener("input", atualizarSaldo);
  atualizarSaldo();
});

document.querySelectorAll("form[data-rascunho]").forEach((form) => {
  const consulta = new URLSearchParams(window.location.search);
  const selecionar = consulta.get("selecionar");
  consulta.delete("selecionar");
  const texto = consulta.toString();
  const chave = `rascunho:${window.location.pathname}${texto ? `?${texto}` : ""}`;
  const ignorados = new Set(["csrfmiddlewaretoken", "proximo", "senha"]);

  const coletar = () => {
    const dados = {};
    Array.from(form.elements).forEach((el) => {
      if (!el.name || ignorados.has(el.name) || el.type === "password" || el.type === "file") {
        return;
      }
      if (el.type === "checkbox" || el.type === "radio") {
        dados[el.name] = dados[el.name] || [];
        if (el.checked) {
          dados[el.name].push(el.value);
        }
      } else if (el.multiple) {
        dados[el.name] = Array.from(el.selectedOptions).map((o) => o.value);
      } else {
        dados[el.name] = [el.value];
      }
    });
    return dados;
  };

  form.querySelectorAll("[data-rascunho-link]").forEach((link) => {
    link.addEventListener("click", () => {
      sessionStorage.setItem(chave, JSON.stringify(coletar()));
    });
  });

  const salvo = sessionStorage.getItem(chave);
  if (salvo) {
    sessionStorage.removeItem(chave);
    const dados = JSON.parse(salvo);
    const estado = form.querySelector("#id_estado");
    const municipio = form.querySelector("#id_municipio");
    if (estado && municipio && dados.municipio?.[0]) {
      municipio.add(new Option("", dados.municipio[0], true, true));
    }
    Array.from(form.elements).forEach((el) => {
      const valores = dados[el.name];
      if (!el.name || !valores) {
        return;
      }
      if (el.type === "checkbox" || el.type === "radio") {
        el.checked = valores.includes(el.value);
      } else if (el.multiple) {
        Array.from(el.options).forEach((o) => {
          o.selected = valores.includes(o.value);
        });
      } else if (el.name !== "municipio" || !estado) {
        el.value = valores[0];
      }
    });
    if (estado && estado.value) {
      estado.dispatchEvent(new Event("change"));
    }
    const fazenda = form.querySelector("#id_fazenda");
    if (fazenda && fazenda.value) {
      fazenda.dataset.preservarPlantio = "true";
      fazenda.dispatchEvent(new Event("change"));
    }
    form.querySelectorAll("input[data-mask]").forEach((campo) => {
      campo.dispatchEvent(new Event("input"));
    });
    // Campos que mostram ou escondem outros precisam refletir o valor restaurado.
    ["#id_tipo", "#id_tipo_usuario", "#id_modalidade"].forEach((seletor) => {
      form.querySelector(seletor)?.dispatchEvent(new Event("change"));
    });
  }

  if (selecionar) {
    const [campo, pk] = selecionar.split(":");
    const alvo = form.querySelector(`[name="${campo}"]`);
    if (alvo && Array.from(alvo.options).some((o) => o.value === pk)) {
      alvo.value = pk;
      alvo.dispatchEvent(new Event("change"));
    }
  }
});

document.querySelectorAll("select[data-padroes-pais]").forEach((pais) => {
  let padroes = {};
  try {
    padroes = JSON.parse(pais.dataset.padroesPais);
  } catch (erro) {
    console.error("Padrões de país inválidos.", erro);
    return;
  }
  pais.addEventListener("change", () => {
    Object.entries(padroes[pais.value] || {}).forEach(([nome, valor]) => {
      const campo = pais.form?.querySelector(`[name="${nome}"]`);
      if (campo) {
        campo.value = valor;
      }
    });
  });
});

// Menu lateral: recolher/expandir e lembrar as seções abertas.
(() => {
  const raiz = document.documentElement;
  const botao = document.querySelector("[data-menu-recolher]");
  const secoes = document.querySelectorAll(".menu-secao[data-secao]");
  const ler = (chave) => {
    try {
      return localStorage.getItem(chave);
    } catch (erro) {
      return null;
    }
  };
  const gravar = (chave, valor) => {
    try {
      localStorage.setItem(chave, valor);
    } catch (erro) {
      // Sem armazenamento: o menu só não lembra a preferência.
    }
  };
  const atualizarBotao = () => {
    if (!botao) {
      return;
    }
    const recolhido = raiz.classList.contains("menu-recolhido");
    botao.setAttribute("aria-expanded", String(!recolhido));
    botao.title = recolhido ? "Expandir o menu" : "Recolher o menu";
    const texto = botao.querySelector(".menu-texto");
    if (texto) {
      texto.textContent = recolhido ? "Expandir menu" : "Recolher menu";
    }
  };
  const recolher = (sim) => {
    raiz.classList.toggle("menu-recolhido", sim);
    gravar("rvcfc-menu", sim ? "recolhido" : "aberto");
    atualizarBotao();
  };
  botao?.addEventListener("click", () => {
    recolher(!raiz.classList.contains("menu-recolhido"));
  });
  atualizarBotao();

  let abertas = [];
  try {
    abertas = JSON.parse(ler("rvcfc-secoes") || "[]");
  } catch (erro) {
    abertas = [];
  }
  secoes.forEach((secao) => {
    if (abertas.includes(secao.dataset.secao)) {
      secao.open = true;
    }
    const resumo = secao.querySelector("summary");
    resumo?.addEventListener("click", (evento) => {
      // Recolhido: clicar numa seção abre o menu já com ela aberta.
      if (raiz.classList.contains("menu-recolhido")) {
        evento.preventDefault();
        secao.open = true;
        recolher(false);
      }
    });
    secao.addEventListener("toggle", () => {
      const atuais = Array.from(secoes)
        .filter((item) => item.open)
        .map((item) => item.dataset.secao);
      gravar("rvcfc-secoes", JSON.stringify(atuais));
    });
  });
})();
