# Cria (ou recria) as rotinas diarias do AUTO SERE no Agendador de Tarefas do Windows.
# Segunda a sexta; quem decide se ha aula e o proprio programa (calendario letivo), entao feriado/ferias nao precisam de ajuste aqui.
# Etapas avulsas (turmas, alunos, prematricula, origem, consultas, avisos, planilha) continuam disponiveis:
#   python -m src.automacao.rotina_diaria <etapa>
#   .\agendar_rotinas.ps1            cria/atualiza as tarefas
#   .\agendar_rotinas.ps1 -Remover   apaga todas
param([switch]$Remover)
$ErrorActionPreference = "Stop"
$raiz   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $raiz "runtime\python\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $raiz ".venv\Scripts\pythonw.exe" }
if (-not (Test-Path $python)) { Write-Host "ERRO: ambiente nao encontrado. Rode INSTALAR_WINDOWS.bat." -ForegroundColor Red; exit 1 }

# Duas tarefas: a virada de ano (07:50) e a SEQUENCIA diaria (08:00), que roda turmas -> alunos novos -> pre-matricula ->
# origem -> CEP/SISREG -> avisos da home -> planilha, uma depois da outra, parando se uma etapa obrigatoria falhar.
# Rodar a sequencia de novo no mesmo dia continua de onde parou. As tarefas antigas (uma por horario) sao removidas
# para a rotina nao rodar duas vezes.
$rotinas = @(
    @{ Hora = "07:50"; Etapa = "virada" },
    @{ Hora = "08:00"; Etapa = "sequencia" }
)
$legadas = @(
    "AUTO SERE - 08h00 turmas",
    "AUTO SERE - 09h00 alunos",
    "AUTO SERE - 10h00 planilha",
    "AUTO SERE - 11h00 consultas"
)
foreach ($antiga in $legadas) {
    if ($null -ne (Get-ScheduledTask -TaskName $antiga -ErrorAction SilentlyContinue)) {
        Unregister-ScheduledTask -TaskName $antiga -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removida (tarefa antiga, substituida pela sequencia): $antiga"
    }
}
$dias = "Monday","Tuesday","Wednesday","Thursday","Friday"

foreach ($r in $rotinas) {
    $nome = "AUTO SERE - $($r.Hora.Replace(':','h')) $($r.Etapa)"   # sem ":" (o Agendador nao aceita no nome)
    if ($Remover) {
        Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removida: $nome"
        continue
    }
    $acao = New-ScheduledTaskAction -Execute $python -Argument "-m src.automacao.rotina_diaria $($r.Etapa)" -WorkingDirectory $raiz
    $gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dias -At $r.Hora
    # StartWhenAvailable: se o PC estava desligado no horario, roda assim que ligar.
    $conf = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    try {
        Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $conf -Force -ErrorAction Stop | Out-Null
        Write-Host "Criada: $nome"
    } catch {
        Write-Host "FALHOU: $nome -> $($_.Exception.Message)" -ForegroundColor Red
    }
}
if (-not $Remover) { Write-Host "Pronto. Teste com:  python -m src.automacao.rotina_diaria status" }