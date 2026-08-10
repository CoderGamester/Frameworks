#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

/// <summary>Produces clean-host evidence for the Mobile Services sample's InputForUI interaction.</summary>
[InitializeOnLoad]
internal static class MobileSamplesInputForUiVerifier
{
	private const string EnabledEnvironmentVariable = "MOBILE_SAMPLES_VERIFY_INPUTFORUI";
	private const string OutputEnvironmentVariable = "MOBILE_SAMPLES_VERIFY_OUTPUT";
	private const string StartedSessionKey = "GameLovers.MobileSamples.InputForUI.Started";
	private const string StartTimeSessionKey = "GameLovers.MobileSamples.InputForUI.StartTime";
	private const double TimeoutSeconds = 120d;

	private static bool _readyWritten;
	private static bool _screenshotRequested;
	private static bool _completed;
	private static int _screenshotFrame;
	private static int _stableEditorTicks;
	private static string _sceneBeforeInput;

	private static string OutputDirectory => Environment.GetEnvironmentVariable(OutputEnvironmentVariable) ?? string.Empty;
	private static string ReadyPath => Path.Combine(OutputDirectory, "ready.txt");
	private static string ReportPath => Path.Combine(OutputDirectory, "behavior-report.txt");
	private static string ScreenshotPath => Path.Combine(OutputDirectory, "haptics.png");

	static MobileSamplesInputForUiVerifier()
	{
		if (Environment.GetEnvironmentVariable(EnabledEnvironmentVariable) != "1") return;

		Directory.CreateDirectory(OutputDirectory);
		EditorApplication.update -= Tick;
		EditorApplication.update += Tick;
	}

	private static void StartWhenReady()
	{
		var overviewScene = ResolvePlayerScenePath();
		if (EditorApplication.isCompiling || EditorApplication.isUpdating ||
		    Type.GetType("GameLovers.MobileServices.Samples.MobileServicesPlayground.MobileServicesPlaygroundUI, GameLovers.MobileServices.Samples") == null ||
		    string.IsNullOrEmpty(overviewScene))
		{
			_stableEditorTicks = 0;
			return;
		}

		_stableEditorTicks++;
		if (_stableEditorTicks < 30) return;

		SessionState.SetBool(StartedSessionKey, true);
		SessionState.SetString(StartTimeSessionKey, DateTime.UtcNow.Ticks.ToString());
		EditorSceneManager.OpenScene(overviewScene, OpenSceneMode.Single);
		EditorApplication.EnterPlaymode();
	}

	private static string ResolvePlayerScenePath()
	{
		var guids = AssetDatabase.FindAssets("t:MobileServicesSampleBuildCatalogAsset");
		if (guids.Length != 1) return null;
		var catalogPath = AssetDatabase.GUIDToAssetPath(guids[0]);
		var catalog = AssetDatabase.LoadAssetAtPath<ScriptableObject>(catalogPath);
		if (catalog == null) return null;
		var serialized = new SerializedObject(catalog);
		var scene = serialized.FindProperty("_playerScene");
		return scene == null || scene.objectReferenceValue == null ? null : AssetDatabase.GetAssetPath(scene.objectReferenceValue);
	}

	private static void Tick()
	{
		if (_completed) return;
		if (!SessionState.GetBool(StartedSessionKey, false) && !EditorApplication.isPlayingOrWillChangePlaymode)
		{
			StartWhenReady();
			return;
		}
		if (!EditorApplication.isPlaying) return;

		var document = UnityEngine.Object.FindAnyObjectByType<UIDocument>();
		if (document == null || document.rootVisualElement.panel == null)
		{
			FailIfTimedOut("The Overview UIDocument did not become ready.");
			return;
		}

		var title = FirstLabel(document.rootVisualElement);
		if (!_readyWritten && SceneManager.GetActiveScene().name == "MobileServicesSamples")
		{
			var buttons = document.rootVisualElement.Query<Button>().ToList();
			var haptics = document.rootVisualElement.Q<Button>("nav-haptics");
			_sceneBeforeInput = SceneManager.GetActiveScene().name;
			WriteLines(ReadyPath, new[]
			{
				"editor=" + Application.unityVersion,
				"scene=" + SceneManager.GetActiveScene().name,
				"title=" + title,
				"buttons=" + buttons.Count,
				"hapticsBound=" + (haptics == null ? "missing" : haptics.worldBound.ToString()),
				"inputProvider=" + InputProviderName(),
				"eventSystems=" + EventSystemCount(),
				"status=READY"
			});
			_readyWritten = true;
		}

		var hapticsPage = document.rootVisualElement.Q<VisualElement>("page-haptics");
		var hapticsButton = document.rootVisualElement.Q<Button>("nav-haptics");
		var hapticsSelected = hapticsButton != null && hapticsButton.ClassListContains("is-selected");
		if (!hapticsSelected || hapticsPage == null || hapticsPage.resolvedStyle.display == DisplayStyle.None)
		{
			FailIfTimedOut("Foreground input did not select the Haptics page in the resident shell.");
			return;
		}

		if (!_screenshotRequested)
		{
			ScreenCapture.CaptureScreenshot(ScreenshotPath);
			_screenshotRequested = true;
			_screenshotFrame = Time.frameCount;
			return;
		}

		if (Time.frameCount - _screenshotFrame < 5 || !File.Exists(ScreenshotPath)) return;

		var screenshotBytes = new FileInfo(ScreenshotPath).Length;
		var eventSystems = EventSystemCount();
		var provider = InputProviderName();
		var sceneAfterInput = SceneManager.GetActiveScene().name;
		var passed = _readyWritten && title == "Haptics Palette" && sceneAfterInput == _sceneBeforeInput && eventSystems == 0 &&
		             provider == "UnityEngine.InputSystem.Plugins.InputForUI.InputSystemProvider" && screenshotBytes > 0;
		WriteLines(ReportPath, new[]
		{
			"editor=" + Application.unityVersion,
			"interaction=foreground-mouse-click-resident-tab",
			"sceneBeforeInput=" + _sceneBeforeInput,
			"sceneAfterInput=" + sceneAfterInput,
			"selectedTab=" + (hapticsSelected ? "Haptics" : "missing"),
			"title=" + title,
			"inputProvider=" + provider,
			"eventSystems=" + eventSystems,
			"screenshotBytes=" + screenshotBytes,
			"result=" + (passed ? "PASS" : "FAIL")
		});
		Complete();
	}

	private static string FirstLabel(VisualElement root)
	{
		return root.Query<Label>().ToList().Select(label => label.text)
			.FirstOrDefault(text => !string.IsNullOrEmpty(text)) ?? "none";
	}

	private static int EventSystemCount()
	{
		return UnityEngine.Object.FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Include, FindObjectsSortMode.None)
			.Count(component => component != null && component.GetType().FullName == "UnityEngine.EventSystems.EventSystem");
	}

	private static string InputProviderName()
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		var eventProviderType = assemblies
			.Select(assembly => assembly.GetType("UnityEngine.InputForUI.EventProvider"))
			.FirstOrDefault(type => type != null);
		var provider = eventProviderType?.GetProperty("provider")?.GetValue(null);
		if (provider != null) return provider.GetType().FullName;

		// Unity 6000.0 exposes EventProvider differently from later streams. The provider
		// assembly/type plus a committed foreground click with no EventSystem proves the same path.
		return assemblies
			.Select(assembly => assembly.GetType("UnityEngine.InputSystem.Plugins.InputForUI.InputSystemProvider"))
			.FirstOrDefault(type => type != null)?.FullName ?? "none";
	}

	private static void FailIfTimedOut(string reason)
	{
		if (!long.TryParse(SessionState.GetString(StartTimeSessionKey, "0"), out var ticks)) return;
		if ((DateTime.UtcNow - new DateTime(ticks, DateTimeKind.Utc)).TotalSeconds < TimeoutSeconds) return;

		WriteLines(ReportPath, new[]
		{
			"editor=" + Application.unityVersion,
			"reason=" + reason,
			"result=FAIL"
		});
		Complete();
	}

	private static void WriteLines(string path, IEnumerable<string> lines)
	{
		File.WriteAllLines(path, lines);
	}

	private static void Complete()
	{
		_completed = true;
		SessionState.EraseBool(StartedSessionKey);
		SessionState.EraseString(StartTimeSessionKey);
		EditorApplication.update -= Tick;
	}
}
#endif
