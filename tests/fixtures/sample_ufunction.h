// Sample Unreal C++ header with UFUNCTION macros used for preprocessor tests.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CombatComponent.generated.h"

UCLASS(Blueprintable, BlueprintType)
class MYGAME_API ACombatActor : public AActor
{
    GENERATED_BODY()

public:

    /**
     * @brief Applies damage to this actor.
     *
     * Reduces the actor's health by DamageAmount.  If health reaches zero the
     * actor is destroyed.
     *
     * @param DamageAmount The amount of damage to apply.
     * @param DamageCauser The actor responsible for the damage.
     */
    UFUNCTION(BlueprintCallable, Category = "Combat")
    void ApplyDamage(float DamageAmount, AActor* DamageCauser);

    /** @brief Heals the actor. */
    UFUNCTION(BlueprintCallable, BlueprintPure = false, Category = "Combat")
    void Heal(float HealAmount);

    /**
     * Called on the server when a projectile hits this actor.
     */
    UFUNCTION(Server, Reliable, WithValidation)
    void Server_OnProjectileHit(FVector HitLocation);

    /** Returns true if this actor is alive. */
    UFUNCTION(BlueprintPure, Category = "Combat")
    bool IsAlive() const;

    /**
     * @brief Exec command: sets health directly (debug only).
     */
    UFUNCTION(Exec)
    void SetHealth(float NewHealth);

    /**
     * @brief Blueprint implementable event fired when the actor takes damage.
     * Override this in Blueprints to react to incoming damage.
     */
    UFUNCTION(BlueprintImplementableEvent, Category = "Combat|Events")
    void OnDamageTaken(float DamageAmount);
};
