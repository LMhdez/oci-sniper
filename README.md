# OCI Sniper — ferramenta experimental de capacidade OCI

> **AVISO: não executar nem ativar o workflow agendado sem auditoria de custos e autorização explícita.** Este repositório é independente do servidor Minecraft Azure e não é uma dependência de mc-start.

## Objetivo

Contém protótipos Python para tentar criar uma instância Oracle Cloud Compute ARM (VM.Standard.A1.Flex), localmente ou através de GitHub Actions. O código tenta vários Availability Domains e tamanhos.

**Não existe garantia de que a instância obtida seja Always Free, que a capacidade esteja disponível ou que todos os recursos associados tenham custo zero.** O código inclui um boot volume de 200 GB e configura rede/IP públicos; elegibilidade, quotas e preços dependem da conta/região/recursos atuais. A criação de uma instância pode gerar faturação. O requisito do projeto MC SERVER é custo total pessoal de **0,00 € / $0,00**; por isso, este repo fica em estado de auditoria e não deve ser executado até se provar documentalmente que todos os recursos são gratuitos.

## Estado e riscos encontrados na revisão estática

- .github/workflows/sniper.yml contém um cron de 10 em 10 minutos, além de execução manual. O workflow pode tentar criar recursos automaticamente se os secrets estiverem configurados.
- sniper.py chama OCI Compute LaunchInstance; não é uma consulta read-only.
- oci_sniper.py também envia pedidos POST para criar instâncias.
- setup_network.py cria/atualiza Internet Gateway, route table, security list e subnet; abre SSH TCP 22 e Minecraft TCP 25565 a qualquer origem. É mutável e expõe serviços.
- Os perfis tentados incluem 4 OCPU/24 GB e 2 OCPU/12 GB; o boot volume configurado é 200 GB.
- O README anterior afirmava incorretamente que a execução era gratuita/garantidamente segura e descrevia flags que não correspondem ao parser atual. Não confiar nas instruções antigas.
- Os scripts incluem identificadores fixos de recursos e uma chave SSH pública. Não são uma chave privada, mas são dados de infraestrutura que não devem ser replicados em documentação externa.
- O código local e o workflow têm interfaces/configurações diferentes; não assumir paridade.

## Ficheiros

- oci_sniper.py: cliente REST OCI com assinatura RSA e loop de criação; lê ~/.oci/config. Tem --dry-run, mas confirmar comportamento no código antes de usar.
- sniper.py: cliente OCI SDK; lê credenciais de environment variables e tenta criar instâncias.
- setup_network.py: cria/atualiza componentes de rede OCI. **Não executar** sem revisão de custo, exposição e rollback.
- .github/workflows/sniper.yml: execução agendada e manual de sniper.py.
- subnet_id.txt: artefacto local histórico; não assumir que o recurso ainda existe ou que o ID é válido.

## Regras de segurança

- Nunca colocar chave privada PEM, config OCI, tokens, webhooks ou credenciais em GitHub, logs, issues ou outputs.
- Nunca imprimir environment variables nem conteúdo de ~/.oci/config.
- Não publicar IDs de tenancy, compartment, subnet, image ou fingerprints em documentação pública.
- Qualquer comando que possa devolver segredos deve ser filtrado antes de mostrar a saída; se não for possível garantir, não mostrar.
- Não executar setup_network.py: pode abrir SSH/Minecraft à Internet e alterar recursos existentes.
- Não executar o sniper: pode criar recursos com custos. A existência de um plano Free não prova que cada SKU, boot volume, IP, tráfego ou recurso adicional é gratuito.
- Não fazer chamadas de criação até confirmar elegibilidade Always Free atual, quotas, custo de boot volume/IP/armazenamento/tráfego e ausência de outros recursos faturáveis.
- Não usar créditos como substituto de gratuitidade. Limite de custo permitido: 0,00 €.

## Processo para agentes de IA

1. Ler este README e .github/workflows/README.md.
2. Ler os scripts completos antes de qualquer sugestão operacional.
3. Classificar cada função/API call: GET/read-only ou POST/PUT/mutável/criação.
4. Não executar o cron, workflow manual, scripts de criação ou setup de rede.
5. Validar sintaxe/testes offline sem credenciais reais.
6. Se for necessário retomar este projeto, primeiro apresentar inventário de recursos OCI e estimativa documentada de custo zero — apenas leitura — e pedir confirmação antes de qualquer alteração.
7. Distinguir Always Free elegível, Free Trial/créditos e recursos com preço normal.

## Nota de manutenção

Este README corrige as instruções antigas que afirmavam que a execução do cron era gratuita e que o uso do script não podia causar bloqueios. Essas afirmações não estavam demonstradas. Não usar valores de limites do GitHub Actions ou OCI sem confirmar a política atual da conta.
