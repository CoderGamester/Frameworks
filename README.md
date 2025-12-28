# GameLovers Frameworks (Unity)

Unity 6 project used to **develop, test, and validate** GameLovers Unity Package Manager (UPM) packages.

Most packages in this repo live under `Packages/` as **git submodules** (see `.gitmodules`). Each package is intended to be usable as a standalone open-source Unity package.

## What you get here

- **A Unity “host” project**: useful for running samples and tests while developing packages.
- **Embedded packages**: each one is a UPM package (has its own `package.json`, `README.md`, `CHANGELOG.md`, etc.).

## Packages in this repo

Packages are referenced as submodules:

| Package | Purpose | Links |
| --- | --- | --- |
| `com.gamelovers.uiservice` | UI orchestration service (presenters, layers, sets, Addressables loading, optional analytics, editor tooling) | [Repo](https://github.com/CoderGamester/com.gamelovers.uiservice) · [README](Packages/com.gamelovers.uiservice/README.md) |
| `com.gamelovers.assetsimporter` | Asset import tooling | [Repo](https://github.com/CoderGamester/Unity-AssetsImporter) |
| `com.gamelovers.configsprovider` | Configs provider utilities | [Repo](https://github.com/CoderGamester/Unity-ConfigsProvider) |
| `com.gamelovers.dataextensions` | Data type extensions utilities | [Repo](https://github.com/CoderGamester/Unity-DataTypeExtensions) |
| `com.gamelovers.googlesheetimporter` | Google Sheets importer | [Repo](https://github.com/CoderGamester/Unity-GoogleSheet-Importer) |
| `com.gamelovers.inputextensions` | Input utilities/extensions | [Repo](https://github.com/CoderGamester/com.gamelovers.inputextensions) |
| `com.gamelovers.nativeui` | Native UI helpers | [Repo](https://github.com/CoderGamester/com.gamelovers.nativeui) |
| `com.gamelovers.notificationservice` | Notification service utilities | [Repo](https://github.com/CoderGamester/com.gamelovers.notificationservice) |
| `com.gamelovers.services` | General services utilities | [Repo](https://github.com/CoderGamester/Services) |
| `com.gamelovers.statechart` | Statechart / HFSM utilities | [Repo](https://github.com/CoderGamester/Statechart-HFSM) |

Tip: if a package folder is empty on first clone, you likely forgot to fetch submodules.

## Getting started (this repo)

### Clone with submodules

```bash
git clone --recurse-submodules <this-repo-url>
```

Or, if you already cloned:

```bash
git submodule update --init --recursive
```

### Open in Unity

- **Unity**: 6000.0+
- Open the project root in Unity Hub / Unity Editor.

## UiService (highlight)

`com.gamelovers.uiservice` is the most UI-centric package here. It provides:

- A **`UiPresenter`** base class (+ `UiPresenter<TData>`) with lifecycle (`OnInitialized`, `OnOpened`, `OnClosed`, `OnSetData`).
- An **`IUiService` / `UiService`** API to load/open/close/unload presenters (async via UniTask).
- Optional **analytics** (`IUiAnalytics`) and **Editor tools** under `Tools/UI Service/*`.

Read the full docs here: `Packages/com.gamelovers.uiservice/README.md`.

## Contributing

- For package changes, contribute directly to the package repository (each `Packages/com.gamelovers.*` is a submodule).
- When updating a package, also update its `README.md` / `CHANGELOG.md` if behavior or API changes.
- See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.

## License

Licensing is defined per package. For example, UiService is MIT: `Packages/com.gamelovers.uiservice/LICENSE.md`.
