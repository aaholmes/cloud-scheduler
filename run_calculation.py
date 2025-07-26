#!/usr/bin/env python3
"""
Run computational calculations.
This script serves as an example for computational workloads - modify for your specific needs.
Originally designed for quantum chemistry calculations using PySCF and SHCI.
"""
import argparse
import os
import sys
import subprocess
import logging
import json
import time
from datetime import datetime
from pyscf import gto, scf, mcscf
from pyscf.tools import fcidump
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('calculation.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def water_dimer_geometry():
    """Return optimized water dimer geometry."""
    # Geometry from literature (optimized at MP2/aug-cc-pVTZ level)
    # Units in Angstrom
    return '''
    O  -1.551007  -0.114520   0.000000
    H  -1.934259   0.762503   0.000000
    H  -0.599677   0.040712   0.000000
    O   1.350625   0.111469   0.000000
    H   1.680398  -0.373741  -0.758561
    H   1.680398  -0.373741   0.758561
    '''


def run_hartree_fock(mol):
    """Run Hartree-Fock calculation."""
    logger.info("Running Hartree-Fock calculation...")
    mf = scf.RHF(mol)
    mf.verbose = 4
    mf.conv_tol = 1e-10
    mf.kernel()
    
    if not mf.converged:
        logger.warning("Hartree-Fock did not converge!")
    
    logger.info(f"HF Energy: {mf.e_tot:.10f} Hartree")
    return mf


def generate_integrals(mf, output_dir, frozen_core=True):
    """Generate FCIDUMP file with molecular integrals."""
    fcidump_path = os.path.join(output_dir, 'FCIDUMP')
    logger.info(f"Generating FCIDUMP file at: {fcidump_path}")
    
    # Determine frozen core orbitals
    mol = mf.mol
    ncore = 0
    if frozen_core:
        # Freeze oxygen 1s orbitals (2 orbitals for 2 oxygen atoms)
        ncore = 2
        logger.info(f"Freezing {ncore} core orbitals")
    
    # Write FCIDUMP
    with open(fcidump_path, 'w') as f:
        if ncore > 0:
            # Create an active space by freezing core orbitals
            nmo = mf.mo_coeff.shape[1]
            ncas = nmo - ncore
            nelecas = mol.nelectron - 2 * ncore
            
            mc = mcscf.CASCI(mf, ncas, nelecas)
            mc.fcisolver.conv_tol = 1e-10
            mc.kernel()
            
            fcidump.from_mo(mol, fcidump_path, mc.mo_coeff[:, ncore:])
            logger.info(f"Active space: {nelecas} electrons in {ncas} orbitals")
        else:
            fcidump.from_scf(mf, f)
            logger.info(f"Full space: {mol.nelectron} electrons in {mf.mo_coeff.shape[1]} orbitals")
    
    return fcidump_path, ncore


def run_shci_calculation(fcidump_path, output_dir, shci_executable=None):
    """Execute the SHCI program with the generated integrals."""
    if shci_executable is None:
        # Look for SHCI executable in common locations
        possible_paths = [
            './shci_program',
            './shci',
            './Dice',
            '../shci_code/shci_program',
            '../shci_code/Dice',
            './bin/shci',
            './bin/Dice'
        ]
        
        for path in possible_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                shci_executable = path
                break
        
        if shci_executable is None:
            logger.warning("SHCI executable not found. Skipping SHCI calculation.")
            logger.info("Tried the following paths: " + ", ".join(possible_paths))
            return None
    
    logger.info(f"Using SHCI executable: {shci_executable}")
    
    # Create SHCI input file
    shci_input = os.path.join(output_dir, 'shci.inp')
    with open(shci_input, 'w') as f:
        f.write(f"fcidump {fcidump_path}\n")
        f.write("epsilon1 1e-6\n")  # Variational threshold
        f.write("epsilon2 1e-8\n")  # PT threshold
        f.write("targetError 1e-5\n")
        f.write("dE 1e-6\n")
        f.write("maxIter 20\n")
        f.write("nPTiter 0\n")  # No perturbation for initial test
        f.write("DoRDM\n")
    
    # Run SHCI
    shci_output = os.path.join(output_dir, 'shci.out')
    shci_command = [shci_executable, shci_input]
    
    logger.info(f"Executing SHCI command: {' '.join(shci_command)}")
    
    start_time = time.time()
    try:
        with open(shci_output, 'w') as out_f:
            process = subprocess.run(
                shci_command,
                stdout=out_f,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=output_dir
            )
        
        elapsed_time = time.time() - start_time
        
        if process.returncode == 0:
            logger.info(f"SHCI calculation completed successfully in {elapsed_time:.2f} seconds")
            
            # Try to extract energy from output
            try:
                with open(shci_output, 'r') as f:
                    for line in f:
                        if 'Variational Energy' in line or 'Energy' in line:
                            logger.info(f"SHCI result: {line.strip()}")
            except:
                pass
                
        else:
            logger.error(f"SHCI calculation failed with return code {process.returncode}")
            logger.error(f"Check log file: {shci_output}")
            
    except Exception as e:
        logger.error(f"Error running SHCI: {e}")
        
    return shci_output


def save_results_summary(output_dir, mol, mf, basis, calculation_time):
    """Save a summary of the calculation results."""
    summary = {
        'timestamp': datetime.now().isoformat(),
        'molecule': 'water_dimer',
        'basis': basis,
        'num_atoms': mol.natm,
        'num_electrons': mol.nelectron,
        'num_basis_functions': mol.nao_nr(),
        'hf_energy': float(mf.e_tot),
        'hf_converged': bool(mf.converged),
        'calculation_time_seconds': calculation_time,
        'mo_energies': mf.mo_energy.tolist(),
        'dipole_moment': mol.dip_moment(dm=mf.make_rdm1()).tolist()
    }
    
    summary_path = os.path.join(output_dir, 'calculation_summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"Results summary saved to: {summary_path}")
    
    # Also create a human-readable summary
    readable_path = os.path.join(output_dir, 'results.txt')
    with open(readable_path, 'w') as f:
        f.write("Water Dimer SHCI Calculation Results\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Timestamp: {summary['timestamp']}\n")
        f.write(f"Basis Set: {basis}\n")
        f.write(f"Number of atoms: {mol.natm}\n")
        f.write(f"Number of electrons: {mol.nelectron}\n")
        f.write(f"Number of basis functions: {mol.nao_nr()}\n")
        f.write(f"HF Energy: {mf.e_tot:.10f} Hartree\n")
        f.write(f"HF Converged: {mf.converged}\n")
        f.write(f"Calculation time: {calculation_time:.2f} seconds\n")
        f.write(f"\nDipole moment: {mol.dip_moment(dm=mf.make_rdm1())}\n")


def main():
    """Main function to run the calculation."""
    parser = argparse.ArgumentParser(description="Run computational calculation (example: quantum chemistry)")
    parser.add_argument("--basis", default="aug-cc-pVDZ", 
                       help="Basis set (default: aug-cc-pVDZ)")
    parser.add_argument("--output_dir", default="compute_output",
                       help="Directory for output files")
    parser.add_argument("--frozen_core", action="store_true", default=True,
                       help="Freeze core orbitals")
    parser.add_argument("--shci_executable", 
                       help="Path to SHCI executable")
    
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    logger.info("="*60)
    logger.info("Starting Computational Calculation")
    logger.info("="*60)
    logger.info(f"Basis set: {args.basis}")
    logger.info(f"Output directory: {args.output_dir}")
    
    start_time = time.time()
    
    try:
        # Setup molecule
        logger.info("Setting up water dimer molecule...")
        mol = gto.Mole()
        mol.atom = water_dimer_geometry()
        mol.basis = args.basis
        mol.symmetry = False  # C1 symmetry
        mol.charge = 0
        mol.spin = 0  # Singlet
        mol.build()
        
        logger.info(f"Molecule built: {mol.natm} atoms, {mol.nelectron} electrons")
        logger.info(f"Basis functions: {mol.nao_nr()}")
        
        # Run Hartree-Fock
        mf = run_hartree_fock(mol)
        
        # Generate integrals
        fcidump_path, ncore = generate_integrals(mf, args.output_dir, args.frozen_core)
        
        # Run SHCI if executable is available
        shci_output = run_shci_calculation(fcidump_path, args.output_dir, args.shci_executable)
        
        # Calculate total time
        total_time = time.time() - start_time
        
        # Save results summary
        save_results_summary(args.output_dir, mol, mf, args.basis, total_time)
        
        logger.info("="*60)
        logger.info(f"Calculation completed successfully in {total_time:.2f} seconds")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Calculation failed: {e}")
        raise


if __name__ == "__main__":
    main()