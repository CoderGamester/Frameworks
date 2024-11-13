using UnityEngine;

namespace GameLoversEditor.AssetsImporter
{
	public class GeneratorAssetConfigImporter : AssetsConfigsGeneratorImporter<GameObject>
	{
		public override string TIdName => "GeneratorIds";

		public override string TScriptableObjectName => "GeneratorConfigs";
	}
}