// Sample Unreal C++ header with UPROPERTY macros used for preprocessor tests.
#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "CharacterStats.generated.h"

USTRUCT(BlueprintType)
struct MYGAME_API FWeaponInfo
{
    GENERATED_BODY()

    /** @brief Base damage of the weapon. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapon|Stats")
    float BaseDamage = 10.0f;

    /** @brief Display name shown in the inventory UI. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly,
              meta = (DisplayName = "Weapon Name", ToolTip = "Name shown in inventory"))
    FString WeaponName;
};

UCLASS(Blueprintable, BlueprintType)
class MYGAME_API UCharacterStats : public UObject
{
    GENERATED_BODY()

public:

    /** @brief Maximum health of the character. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stats|Health")
    float MaxHealth = 100.0f;

    /** Current health — exposed read-only in Blueprints. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stats|Health")
    float CurrentHealth;

    /**
     * @brief Experience points accumulated this session.
     * Not saved between sessions.
     */
    UPROPERTY(Transient, VisibleAnywhere, BlueprintReadOnly, Category = "Stats|XP")
    int32 SessionXP = 0;

    /** @brief Saved high-score. Persisted in SaveGame objects. */
    UPROPERTY(SaveGame, EditDefaultsOnly, BlueprintReadOnly, Category = "Stats|Score")
    int32 HighScore = 0;
};
