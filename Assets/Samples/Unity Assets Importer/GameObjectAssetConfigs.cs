using GameLovers.AssetsImporter;
using UnityEngine;

namespace GameLoversEditor.AssetsImporter
{
	public enum GameObjectAssetType
	{
		New_Prefab_1,
		New_Prefab_2,
		New_Prefab_3,
		New_Prefab_4,
		New_Prefab
	}
	public class GameObjectAssetConfigs : AssetConfigsScriptableObject<GameObjectAssetType, GameObject>
	{
	}
}

