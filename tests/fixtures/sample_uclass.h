// Sample Unreal C++ header with UCLASS / UENUM / UDELEGATE macros.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "SampleClass.generated.h"

UENUM(BlueprintType)
enum class ECharacterState : uint8
{
    Idle     UMETA(DisplayName = "Idle"),
    Running  UMETA(DisplayName = "Running"),
    Jumping  UMETA(DisplayName = "Jumping"),
    Dead     UMETA(DisplayName = "Dead"),
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnHealthChanged, float, NewHealth);

/**
 * @brief Base playable character class.
 *
 * Extend this class in Blueprints to create player-controlled characters.
 */
UCLASS(Abstract, Blueprintable)
class MYGAME_API ABaseCharacter : public ACharacter
{
    GENERATED_BODY()

public:

    /**
     * @brief Delegate broadcast when health changes.
     * Bind this in Blueprints to update UI health bars.
     */
    UPROPERTY(BlueprintAssignable, Category = "Character|Events")
    FOnHealthChanged OnHealthChanged;

    /** @brief Current movement state of the character. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Character|State")
    ECharacterState CharacterState;

    /**
     * @brief Kills the character immediately.
     * @note Authority only — called via a Server RPC.
     */
    UFUNCTION(Server, Reliable, BlueprintCallable, Category = "Character|Combat")
    void Server_Kill();
};
