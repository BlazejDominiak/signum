; Skrypt Inno Setup 6 dla Signum.
; Wersja jest przekazywana z scripts/build_installer.ps1: /DMyAppVersion=x.y.z
; Budowanie ręczne: ISCC.exe installer\signum.iss /DMyAppVersion=1.0.0

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppName "Signum"
#define MyAppPublisher "Blazej"
#define MyAppExeName "Signum.exe"

[Setup]
; Stały AppId pozwala poprawnie aktualizować/odinstalowywać kolejne wersje.
AppId={{6D6C3F52-9C1B-4E6A-9A57-2B1FBD6A7E31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}.0
VersionInfoProductTextVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; Instalacja per-user (bez uprawnień administratora); użytkownik może wybrać inaczej.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=Signum-Setup-{#MyAppVersion}
SetupIconFile=..\src\signum\ui\resources\signum.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=130,130
MinVersion=10.0.19045
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\Signum-6D6C3F52-9C1B-4E6A-9A57-2B1FBD6A7E31
CloseApplications=yes
CloseApplicationsFilter=Signum.exe
RestartApplications=no

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.RiskPageTitle=Document and AI risk awareness
english.RiskPageDescription=Read the notice and confirm each point before continuing.
english.RiskCheckPurpose=I understand that the program is educational and is not suitable for commercial use.
english.RiskCheckDocuments=I will use the program only with sample documents that contain no personal or sensitive data.
english.RiskCheckLocal=Local AI processes the document contents.
english.RiskCheckRemote=Remote AI receives the document contents, which means they leave the computer over the internet and are processed by an external service.
english.RiskRequired=Confirm all four points to continue.
english.RequirementsNote=Ollama, models, libraries and Python are external components that must be downloaded from trusted sources; the author of Signum accepts no responsibility for them.
english.ComponentsTitle=Components and local AI
english.ComponentsDescription=Choose components using the detected hardware and installation status.
english.Installed=files detected — operation will be tested
english.NotDetected=not detected
english.ServiceDetected=running service detected
english.ModelsUnknown=model status could not be verified
english.Recommended=recommended for this GPU
english.JevUnavailable=requires NVIDIA with 16 GB VRAM
english.GpuUnknown=GPU memory could not be determined. No large model will be recommended automatically.
english.GpuDetected=Detected GPU:
english.RecommendSmall=Recommendation: Gemma 4 E2B for an 8 GB GPU.
english.RecommendLarge=Recommended model: Gemma 4 12B (16 GB VRAM).
english.RecommendNone=Below 8 GB dedicated VRAM: use an existing service or remote API. Local models may use slow CPU processing.
english.ComponentApp=Signum application (required)
english.ComponentOllama=Ollama — third-party local AI service
english.ComponentSmall=Gemma 4 E2B
english.ComponentLarge=Gemma 4 12B
english.ComponentJev=Jev — signature detection (Python + libraries + model)
english.ComponentJevK5=JevK5 — document classification (Python + libraries + model)
english.SmallDetails=Signatures and classification; 8 GB VRAM; ~4.6 GB download.
english.LargeDetails=Signatures and classification; 16 GB VRAM; ~8 GB download.
english.JevDetails=NVIDIA 16 GB; model and external libraries; ~15 GB download.
english.TypeApp=Signum only / existing AI / remote API
english.TypeCustom=Choose local AI components
english.RecommendButton=Select recommended components
english.StorageTitle=Where to store local AI
english.StorageDescription=Models and external libraries can occupy tens of GB.
english.StoragePrompt=Choose a folder on a drive with enough free space. Allow at least 20 GB for Ollama with one model, or 35 GB for each of Jev / JevK5. Components are downloaded after Signum is copied. They remain separate from the application and are not removed when Signum is uninstalled.
english.StorageLabel=AI models and libraries folder:
english.StorageInvalid=Choose an absolute path on an existing drive, outside the Signum application folder.
english.JevUnsupported=Jev and JevK5 need an NVIDIA GPU with at least 16 GB dedicated VRAM. Uncheck Jev / JevK5 or choose a supported computer.
english.LargeWarning=The selected large Ollama model is recommended for 16 GB VRAM. On this GPU, some work may run on the CPU and be much slower. Continue?
polish.RiskPageTitle=Świadomość ryzyka dla dokumentów i AI
polish.RiskPageDescription=Przeczytaj informację i potwierdź każdy punkt przed kontynuowaniem.
polish.RiskCheckPurpose=Rozumiem, że program jest edukacyjny i nie nadaje się do użytku komercyjnego.
polish.RiskCheckDocuments=Będę korzystać z programu tylko na dokumentach przykładowych, niezawierających danych osobowych ani danych wrażliwych.
polish.RiskCheckLocal=Lokalne AI przetwarza treść dokumentów.
polish.RiskCheckRemote=Zdalne AI otrzymuje treść dokumentów, co oznacza, że opuszczają komputer przez sieć internetową i są przetwarzane przez zewnętrzną usługę.
polish.RiskRequired=Aby kontynuować, potwierdź wszystkie cztery punkty.
polish.RequirementsNote=Ollama, modele, biblioteki i Python są składnikami zewnętrznymi, które należy pobierać ze sprawdzonych źródeł; autor Signum nie bierze za nie odpowiedzialności.
polish.ComponentsTitle=Składniki i lokalne AI
polish.ComponentsDescription=Wybierz składniki na podstawie wykrytego sprzętu i stanu instalacji.
polish.Installed=wykryto pliki — działanie zostanie sprawdzone
polish.NotDetected=nie wykryto
polish.ServiceDetected=wykryto działającą usługę
polish.ModelsUnknown=nie udało się sprawdzić zainstalowanych modeli
polish.Recommended=zalecany dla tej karty
polish.JevUnavailable=wymaga NVIDIA z 16 GB VRAM
polish.GpuUnknown=Nie udało się odczytać pamięci GPU. Instalator nie wybierze automatycznie dużego modelu.
polish.GpuDetected=Wykryta karta:
polish.RecommendSmall=Propozycja: Gemma 4 E2B dla karty 8 GB.
polish.RecommendLarge=Zalecany model: Gemma 4 12B (16 GB VRAM).
polish.RecommendNone=Poniżej 8 GB dedykowanej pamięci: użyj posiadanej usługi lub API. Lokalny model może działać powoli na procesorze.
polish.ComponentApp=Program Signum (wymagany)
polish.ComponentOllama=Ollama — zewnętrzny program do lokalnego AI
polish.ComponentSmall=Gemma 4 E2B
polish.ComponentLarge=Gemma 4 12B
polish.ComponentJev=Jev — sprawdzanie podpisów (Python + biblioteki + model)
polish.ComponentJevK5=JevK5 — kategoryzacja (Python + biblioteki + model)
polish.SmallDetails=Podpisy i kategoryzacja; 8 GB VRAM; ~4,6 GB do pobrania.
polish.LargeDetails=Podpisy i kategoryzacja; 16 GB VRAM; ~8 GB do pobrania.
polish.JevDetails=NVIDIA 16 GB; model i zewnętrzne biblioteki; ~15 GB do pobrania.
polish.TypeApp=Tylko Signum / posiadane AI / zdalne API
polish.TypeCustom=Wybór składników lokalnego AI
polish.RecommendButton=Zaznacz proponowane składniki
polish.StorageTitle=Miejsce na lokalne AI
polish.StorageDescription=Modele i zewnętrzne biblioteki zajmują nawet kilkadziesiąt GB.
polish.StoragePrompt=Wybierz katalog na dysku z wolnym miejscem. Dla Ollamy z jednym modelem przeznacz co najmniej 20 GB, dla każdego z Jev / JevK5 — 35 GB. Pobieranie rozpocznie się po skopiowaniu Signum. Te składniki są osobne i nie zostaną usunięte przy odinstalowaniu aplikacji.
polish.StorageLabel=Katalog modeli i bibliotek AI:
polish.StorageInvalid=Wybierz pełną ścieżkę na istniejącym dysku, poza katalogiem programu Signum.
polish.JevUnsupported=Pakiety Jev i JevK5 wymagają karty NVIDIA z co najmniej 16 GB dedykowanej pamięci. Odznacz Jev / JevK5 albo użyj zgodnego komputera.
polish.LargeWarning=Wybrany duży model Ollamy jest zalecany dla 16 GB VRAM. Na tej karcie część pracy może trafić na procesor i znacznie zwolnić. Kontynuować?

[Types]
Name: "app"; Description: "{cm:TypeApp}"
Name: "custom"; Description: "{cm:TypeCustom}"; Flags: iscustom

[Components]
Name: "app"; Description: "{cm:ComponentApp}"; Types: app custom; Flags: fixed
Name: "ollama"; Description: "{cm:ComponentOllama}"
Name: "gemma_small"; Description: "{cm:ComponentSmall}"
Name: "gemma_large"; Description: "{cm:ComponentLarge}"
Name: "jev"; Description: "{cm:ComponentJev}"
Name: "jevk5"; Description: "{cm:ComponentJevK5}"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Pliki tylko dla strony świadomości ryzyka. Przy kompresji solid muszą być pierwsze.
Source: "legal\RISK-NOTICE-en.txt"; Flags: dontcopy noencryption
Source: "legal\RISK-NOTICE-pl.txt"; Flags: dontcopy noencryption
Source: "detect-gpu.ps1"; Flags: dontcopy noencryption
Source: "detect-ai.ps1"; Flags: dontcopy noencryption
Source: "..\dist\Signum\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup-local-ai --ai-components ""{code:SelectedAIComponents}"" --ai-directory ""{code:AIStorageDirectory}"" --existing-ollama ""{code:ExistingOllama}"" --existing-ollama-url ""{code:ExistingOllamaURL}"""; WorkingDir: "{app}"; Check: LocalAISelected; Flags: runasoriginaluser
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  RiskPage: TWizardPage;
  RiskMemo: TNewMemo;
  RiskCheckPurpose: TNewCheckBox;
  RiskCheckDocuments: TNewCheckBox;
  RiskCheckLocal: TNewCheckBox;
  RiskCheckRemote: TNewCheckBox;
  HardwareSummary: TNewStaticText;
  ComponentsNote: TNewStaticText;
  StoragePage: TInputDirWizardPage;
  RecommendButton: TNewButton;
  GpuMemoryMB: Integer;
  GpuVendor: Integer;
  GpuName: String;
  OllamaPath: String;
  OllamaURL: String;
  SmallInstalled: Boolean;
  LargeInstalled: Boolean;
  JevInstalled: Boolean;
  JevK5Installed: Boolean;
  ModelsKnown: Boolean;

function LocalAISelected: Boolean;
begin
  Result := WizardIsComponentSelected('ollama') or WizardIsComponentSelected('jev') or
    WizardIsComponentSelected('jevk5') or
    WizardIsComponentSelected('gemma_small') or WizardIsComponentSelected('gemma_large');
end;

function SelectedAIComponents(Param: String): String;
begin
  Result := 'app';
  if WizardIsComponentSelected('ollama') then Result := Result + ',ollama';
  if WizardIsComponentSelected('gemma_small') then Result := Result + ',ollama\small';
  if WizardIsComponentSelected('gemma_large') then Result := Result + ',ollama\large';
  if WizardIsComponentSelected('jev') then Result := Result + ',jev';
  if WizardIsComponentSelected('jevk5') then Result := Result + ',jevk5';
end;

function ExistingOllama(Param: String): String;
begin
  Result := OllamaPath;
end;

function ExistingOllamaURL(Param: String): String;
begin
  Result := OllamaURL;
end;

function AIStorageDirectory(Param: String): String;
begin
  { Avoid a trailing backslash immediately before the command-line closing quote. }
  Result := AddBackslash(StoragePage.Values[0]) + '.';
end;

procedure DetectGPU;
var
  ExitCode: Integer;
  Info: TArrayOfString;
begin
  ExtractTemporaryFile('detect-gpu.ps1');
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\detect-gpu.ps1') +
    '" -OutputPath "' + ExpandConstant('{tmp}\gpu-info.txt') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0) then
    if LoadStringsFromFile(ExpandConstant('{tmp}\gpu-info.txt'), Info) then
      if GetArrayLength(Info) >= 3 then
      begin
        GpuMemoryMB := StrToIntDef(Info[0], 0);
        GpuVendor := StrToIntDef(Info[1], 0);
        GpuName := Info[2];
      end;
end;

procedure SelectRecommended(Sender: TObject);
var
  Selection: String;
begin
  Selection := 'app';
  if GpuMemoryMB >= 15000 then
    Selection := Selection + ',gemma_large'
  else if GpuMemoryMB >= 7500 then
    Selection := Selection + ',gemma_small';
  if (Selection <> 'app') and (OllamaPath = '') and (OllamaURL = '') then
    Selection := Selection + ',ollama';
  WizardSelectComponents(Selection);
end;

procedure DetectAI;
var
  ExitCode: Integer;
  Info: TArrayOfString;
begin
  ExtractTemporaryFile('detect-ai.ps1');
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\detect-ai.ps1') +
    '" -OutputPath "' + ExpandConstant('{tmp}\ai-info.txt') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0) then
    if LoadStringsFromFile(ExpandConstant('{tmp}\ai-info.txt'), Info) then
      if GetArrayLength(Info) >= 6 then
      begin
        OllamaPath := Info[0];
        OllamaURL := Info[1];
        SmallInstalled := Info[2] = '1';
        LargeInstalled := Info[3] = '1';
        JevInstalled := Info[4] = '1';
        ModelsKnown := Info[5] = '1';
        if GetArrayLength(Info) >= 7 then JevK5Installed := Info[6] = '1';
      end;
end;

procedure UpdateComponentsPage;
var
  OllamaMessage: String;
  Recommendation: String;
  Status: String;
begin
  if OllamaPath <> '' then
    OllamaMessage := 'Ollama: ' + CustomMessage('Installed')
  else if OllamaURL <> '' then
    OllamaMessage := 'Ollama: ' + CustomMessage('ServiceDetected')
  else
    OllamaMessage := 'Ollama: ' + CustomMessage('NotDetected');
  if GpuMemoryMB >= 15000 then
    Recommendation := CustomMessage('RecommendLarge')
  else if GpuMemoryMB >= 7500 then
    Recommendation := CustomMessage('RecommendSmall')
  else if GpuMemoryMB > 0 then
    Recommendation := CustomMessage('RecommendNone')
  else
    Recommendation := CustomMessage('GpuUnknown');
  if GpuMemoryMB > 0 then
    Recommendation := CustomMessage('GpuDetected') + ' ' + GpuName +
      ' (' + IntToStr(GpuMemoryMB) + ' MB VRAM).' + #13#10 + Recommendation;
  HardwareSummary.Caption := Recommendation + #13#10 + OllamaMessage;
  WizardForm.ComponentsList.ItemEnabled[1] := True;
  if not WizardForm.ComponentsList.ItemEnabled[1] then
  begin
    WizardForm.ComponentsList.Checked[1] := False;
    WizardForm.ComponentsList.ItemCaption[1] := OllamaMessage;
  end;
  Status := '';
  if SmallInstalled then Status := ' — ' + CustomMessage('Installed');
  if not ModelsKnown then Status := ' — ' + CustomMessage('ModelsUnknown');
  if (GpuMemoryMB >= 7500) and (GpuMemoryMB < 15000) then
    Status := Status + ' — ' + CustomMessage('Recommended');
  WizardForm.ComponentsList.ItemCaption[2] := CustomMessage('ComponentSmall') + Status;
  if not SmallInstalled then
    WizardForm.ComponentsList.ItemSubItem[2] := CustomMessage('SmallDetails');
  Status := '';
  if LargeInstalled then Status := ' — ' + CustomMessage('Installed');
  if not ModelsKnown then Status := ' — ' + CustomMessage('ModelsUnknown');
  if GpuMemoryMB >= 15000 then Status := Status + ' — ' + CustomMessage('Recommended');
  WizardForm.ComponentsList.ItemCaption[3] := CustomMessage('ComponentLarge') + Status;
  if not LargeInstalled then
    WizardForm.ComponentsList.ItemSubItem[3] := CustomMessage('LargeDetails');
  Status := '';
  if JevInstalled then Status := ' — ' + CustomMessage('Installed');
  if (GpuVendor <> 4318) or (GpuMemoryMB < 15000) then
    Status := Status + ' — ' + CustomMessage('JevUnavailable');
  WizardForm.ComponentsList.ItemCaption[4] := CustomMessage('ComponentJev') + Status;
  if not JevInstalled then
    WizardForm.ComponentsList.ItemSubItem[4] := CustomMessage('JevDetails');
  WizardForm.ComponentsList.ItemEnabled[4] :=
    JevInstalled or ((GpuVendor = 4318) and (GpuMemoryMB >= 15000));
  Status := '';
  if JevK5Installed then Status := ' — ' + CustomMessage('Installed');
  if (GpuVendor <> 4318) or (GpuMemoryMB < 15000) then
    Status := Status + ' — ' + CustomMessage('JevUnavailable');
  WizardForm.ComponentsList.ItemCaption[5] := CustomMessage('ComponentJevK5') + Status;
  WizardForm.ComponentsList.ItemSubItem[5] := CustomMessage('JevDetails');
  WizardForm.ComponentsList.ItemEnabled[5] :=
    JevK5Installed or ((GpuVendor = 4318) and (GpuMemoryMB >= 15000));
end;

function RisksConfirmed: Boolean;
begin
  Result := RiskCheckPurpose.Checked and RiskCheckDocuments.Checked and
    RiskCheckLocal.Checked and RiskCheckRemote.Checked;
end;

procedure RiskCheckClick(Sender: TObject);
begin
  if WizardForm.CurPageID = RiskPage.ID then
    WizardForm.NextButton.Enabled := RisksConfirmed;
end;

procedure RiskLabelClick(Sender: TObject);
var
  Check: TNewCheckBox;
begin
  Check := TNewCheckBox(TNewStaticText(Sender).FocusControl);
  Check.Checked := not Check.Checked;
  RiskCheckClick(Check);
end;

function CreateRiskCheck(const MessageKey: String; var Top: Integer): TNewCheckBox;
var
  TextLabel: TNewStaticText;
  RowHeight: Integer;
begin
  Result := TNewCheckBox.Create(WizardForm);
  Result.Parent := RiskPage.Surface;
  Result.SetBounds(0, Top, ScaleX(20), ScaleY(20));
  Result.OnClick := @RiskCheckClick;

  TextLabel := TNewStaticText.Create(WizardForm);
  TextLabel.Parent := RiskPage.Surface;
  TextLabel.AutoSize := False;
  TextLabel.WordWrap := True;
  TextLabel.ShowAccelChar := False;
  TextLabel.SetBounds(ScaleX(24), Top, RiskPage.SurfaceWidth - ScaleX(24), ScaleY(20));
  TextLabel.Caption := CustomMessage(MessageKey);
  TextLabel.FocusControl := Result;
  TextLabel.OnClick := @RiskLabelClick;
  RowHeight := TextLabel.AdjustHeight;
  if RowHeight < ScaleY(20) then
    RowHeight := ScaleY(20);
  Top := Top + RowHeight + ScaleY(10);
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if WizardSilent and
     (CompareText(ExpandConstant('{param:ACKNOWLEDGERISKS|0}'), '1') <> 0) then
  begin
    SuppressibleMsgBox(
      'Instalacja cicha wymaga jawnego potwierdzenia informacji o ryzyku: ' +
      '/ACKNOWLEDGERISKS=1' + #13#10 + #13#10 +
      'Silent installation requires explicit acknowledgement of the risk ' +
      'notice: /ACKNOWLEDGERISKS=1',
      mbCriticalError, MB_OK, IDOK);
    Result := False;
  end;
end;

procedure InitializeWizard;
var
  NoticeFileName: String;
  CheckTop: Integer;
  MemoHeight: Integer;
begin
  if ActiveLanguage = 'polish' then
    NoticeFileName := 'RISK-NOTICE-pl.txt'
  else
    NoticeFileName := 'RISK-NOTICE-en.txt';

  ExtractTemporaryFile(NoticeFileName);
  RiskPage := CreateCustomPage(wpLicense, CustomMessage('RiskPageTitle'),
    CustomMessage('RiskPageDescription'));

  { Reserve room for wrapped confirmations rather than cutting off long captions. }
  MemoHeight := RiskPage.SurfaceHeight - ScaleY(200);

  RiskMemo := TNewMemo.Create(WizardForm);
  RiskMemo.Parent := RiskPage.Surface;
  RiskMemo.SetBounds(0, 0, RiskPage.SurfaceWidth, MemoHeight);
  RiskMemo.ReadOnly := True;
  RiskMemo.ScrollBars := ssVertical;
  RiskMemo.WordWrap := True;
  RiskMemo.TabStop := False;
  RiskMemo.Lines.LoadFromFile(ExpandConstant('{tmp}\') + NoticeFileName);

  CheckTop := MemoHeight + ScaleY(8);
  RiskCheckPurpose := CreateRiskCheck('RiskCheckPurpose', CheckTop);
  RiskCheckDocuments := CreateRiskCheck('RiskCheckDocuments', CheckTop);
  RiskCheckLocal := CreateRiskCheck('RiskCheckLocal', CheckTop);
  RiskCheckRemote := CreateRiskCheck('RiskCheckRemote', CheckTop);

  { InitializeSetup odrzuca tryb cichy bez jawnego parametru. }
  if WizardSilent then
  begin
    RiskCheckPurpose.Checked := True;
    RiskCheckDocuments.Checked := True;
    RiskCheckLocal.Checked := True;
    RiskCheckRemote.Checked := True;
  end;

  DetectGPU;
  DetectAI;
  WizardForm.SelectComponentsLabel.Visible := False;
  WizardForm.TypesCombo.Visible := False;
  HardwareSummary := TNewStaticText.Create(WizardForm);
  HardwareSummary.Parent := WizardForm.SelectComponentsPage;
  HardwareSummary.AutoSize := False;
  HardwareSummary.WordWrap := True;
  HardwareSummary.SetBounds(0, 0, WizardForm.SelectComponentsPage.ClientWidth, ScaleY(64));
  WizardForm.ComponentsList.SetBounds(0, ScaleY(72),
    WizardForm.SelectComponentsPage.ClientWidth,
    WizardForm.SelectComponentsPage.ClientHeight - ScaleY(166));
  WizardForm.ComponentsList.MinItemHeight := ScaleY(32);
  RecommendButton := TNewButton.Create(WizardForm);
  RecommendButton.Parent := WizardForm.SelectComponentsPage;
  RecommendButton.SetBounds(WizardForm.ComponentsList.Left,
    WizardForm.ComponentsList.Top + WizardForm.ComponentsList.Height + ScaleY(6),
    ScaleX(260), ScaleY(28));
  RecommendButton.Caption := CustomMessage('RecommendButton');
  RecommendButton.OnClick := @SelectRecommended;
  ComponentsNote := TNewStaticText.Create(WizardForm);
  ComponentsNote.Parent := WizardForm.SelectComponentsPage;
  ComponentsNote.AutoSize := False;
  ComponentsNote.WordWrap := True;
  ComponentsNote.SetBounds(0, RecommendButton.Top + RecommendButton.Height + ScaleY(6),
    WizardForm.SelectComponentsPage.ClientWidth, ScaleY(54));
  ComponentsNote.Caption := CustomMessage('RequirementsNote');
  UpdateComponentsPage;

  StoragePage := CreateInputDirPage(wpSelectComponents, CustomMessage('StorageTitle'),
    CustomMessage('StorageDescription'), CustomMessage('StoragePrompt'), False, '');
  StoragePage.Add(CustomMessage('StorageLabel'));
  if DirExists('H:\') then
    StoragePage.Values[0] := 'H:\Tools\SignumAI'
  else
    StoragePage.Values[0] := ExpandConstant('{userdocs}\SignumAI');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = StoragePage.ID) and not LocalAISelected;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = RiskPage.ID then
    WizardForm.NextButton.Enabled := RisksConfirmed
  else if CurPageID = wpSelectComponents then
  begin
    WizardForm.PageNameLabel.Caption := CustomMessage('ComponentsTitle');
    WizardForm.PageDescriptionLabel.Caption := CustomMessage('ComponentsDescription');
    UpdateComponentsPage;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = RiskPage.ID) and not RisksConfirmed then
  begin
    MsgBox(CustomMessage('RiskRequired'), mbInformation, MB_OK);
    Result := False;
  end;
  if CurPageID = wpSelectComponents then
  begin
    if (WizardIsComponentSelected('jev') or WizardIsComponentSelected('jevk5')) and
       ((GpuVendor <> 4318) or (GpuMemoryMB < 15000)) then
    begin
      MsgBox(CustomMessage('JevUnsupported'), mbInformation, MB_OK);
      Result := False;
    end
    else if WizardIsComponentSelected('gemma_large') and (GpuMemoryMB < 15000) then
      Result := MsgBox(CustomMessage('LargeWarning'), mbConfirmation, MB_YESNO) = IDYES;
  end;
  if CurPageID = StoragePage.ID then
    if (ExtractFileDrive(StoragePage.Values[0]) = '') or
       not DirExists(ExtractFileDrive(StoragePage.Values[0]) + '\') or
       (Pos(Lowercase(AddBackslash(WizardDirValue)),
         Lowercase(AddBackslash(StoragePage.Values[0]))) = 1) then
    begin
      MsgBox(CustomMessage('StorageInvalid'), mbInformation, MB_OK);
      Result := False;
    end;
end;
