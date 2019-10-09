from simtk import openmm as mm
from simtk.openmm import app
from simtk.unit import kelvin, kilojoule, mole, nanometer
import torch


# Gas constant in kJ / mol / K
R = 8.314e-3


class OpenMMEnergyAdaptor(torch.autograd.Function):
    @staticmethod
    def forward(ctx, input, openmm_context, temperature):
        device = input.device
        n_batch = input.shape[0]
        n_dim = input.shape[1]
        energies = torch.zeros((n_batch, 1))
        forces = torch.zeros((n_batch, n_dim))

        kBT = R * temperature
        input = input.cpu().detach().numpy()
        for i in range(n_batch):
            # reshape the coordinates and send to OpenMM
            x = input[i, :].reshape(-1, 3)
            openmm_context.setPositions(x)
            state = openmm_context.getState(getForces=True, getEnergy=True)

            # get energy
            energies[i] = (
                state.getPotentialEnergy().value_in_unit(kilojoule / mole) / kBT
            )

            # get forces
            f = (
                state.getForces(asNumpy=True).value_in_unit(
                    kilojoule / mole / nanometer
                )
                / kBT
            )
            forces[i, :] = torch.from_numpy(f.reshape(-1).astype("float32"))
        # Save the forces for the backward step, uploading to the gpu if needed
        ctx.save_for_backward(forces.to(device=device))
        return energies.to(device=device)

    @staticmethod
    def backward(ctx, grad_output):
        forces, = ctx.saved_tensors
        return forces * grad_output, None, None


openmm_energy = OpenMMEnergyAdaptor.apply


def regularize_energy(energy, energy_cut, energy_max):
    # Cap the energy at energy_max
    energy = torch.where(
        energy < energy_max, energy, torch.as_tensor(energy_max, dtype=torch.float32)
    )
    # Make it logarithmic above energy cut and linear below
    energy = torch.where(
        energy < energy_cut, energy - energy_cut, torch.log(energy - energy_cut + 1)
    )
    # Fill any NaNs with energy_max
    energy = torch.where(
        torch.isfinite(energy), energy, torch.as_tensor(energy_max, dtype=torch.float32)
    )
    return energy
