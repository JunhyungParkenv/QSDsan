#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
QSDsan: Quantitative Sustainable Design for sanitation and resource recovery systems

This module is developed by:
    Yalin Li <zoe.yalin.li@gmail.com>
    Joy Zhang <joycheung1994@gmail.com>

Part of this module is based on the biosteam package:
https://github.com/BioSTEAMDevelopmentGroup/biosteam

This module is under the University of Illinois/NCSA Open Source License.
Please refer to https://github.com/QSD-Group/QSDsan/blob/main/LICENSE.txt
for license details.
'''

import numpy as np
from math import pi
from biosteam.units import Pump
from biosteam.units.design_tools.mechanical import (
    brake_efficiency as brake_eff,
    motor_efficiency as motor_eff
    )
from .. import SanUnit
from ..utils import auom, select_pipe, format_str

__all__ = ('Pump', 'HydraulicDelay', 'WWTpump', )


class Pump(SanUnit, Pump):
    '''
    Similar to the :class:`biosteam.units.Pump`,
    but can be initilized with :class:`qsdsan.SanStream` and :class:`qsdsan.WasteStream`,
    and allows dynamic simulation.

    See Also
    --------
    `biosteam.units.Pump <https://biosteam.readthedocs.io/en/latest/units/Pump.html>`_
    '''
    def __init__(self, ID='', ins=None, outs=(), thermo=None, *,
                  P=None, pump_type='Default', material='Cast iron',
                  dP_design=405300, ignore_NPSH=True,
                  init_with='Stream', F_BM_default=None, isdynamic=False):
        SanUnit.__init__(self, ID, ins, outs, thermo,
                         init_with=init_with, F_BM_default=F_BM_default,
                         isdynamic=isdynamic)
        self.P = P
        self.pump_type = pump_type
        self.material = material
        self.dP_design = dP_design
        self.ignore_NPSH = ignore_NPSH

    def reset_cache(self):
        '''Reset cached states.'''
        self._state = None
        for s in self.outs:
            s.empty()

    @property
    def state(self):
        '''The state of the Pump, including component concentrations [mg/L] and flow rate [m^3/d].'''
        if self._state is None: return None
        else:
            return dict(zip(list(self.components.IDs) + ['Q'], self._state))

    @state.setter
    def state(self, QCs):
        QCs = np.asarray(QCs)
        if QCs.shape != (len(self.components)+1, ):
            raise ValueError(f'state must be a 1D array of length {len(self.components) + 1},'
                              'indicating component concentrations [mg/L] and total flow rate [m^3/d]')
        self._state = QCs

    def _init_state(self):
        self._state = self._collect_ins_state()[0]
        self._dstate = self._state * 0.

    def _update_state(self, arr):
        '''updates conditions of output stream based on conditions of the Mixer'''
        self._state = self._outs[0]._state = arr

    def _update_dstate(self):
        '''updates rates of change of output stream from rates of change of the Mixer'''
        self._outs[0]._dstate = self._dstate

    # def _state_locator(self, arr):
    #     '''derives conditions of output stream from conditions of the Mixer'''
    #     dct = {}
    #     dct[self.outs[0].ID] = dct[self.ID] = arr
    #     return dct

    # def _dstate_locator(self, arr):
    #     '''derives rates of change of output stream from rates of change of the Mixer'''
    #     return self._state_locator(arr)

    # def _load_state(self):
    #     '''returns a dictionary of values of state variables within the CSTR and in the output stream.'''
    #     if self._state is None: self._init_state()
    #     return {self.ID: self._state}

    @property
    def ODE(self):
        if self._ODE is None:
            self._compile_ODE()
        return self._ODE

    def _compile_ODE(self):
        def dy_dt(t, QC_ins, QC, dQC_ins):
            self._dstate = dQC_ins[0]
            self._update_dstate()
        self._ODE = dy_dt

    def _define_outs(self):
        dct_y = self._state_locator(self._state)
        out, = self.outs
        Q = dct_y[out.ID][-1]
        Cs = dict(zip(self.components.IDs, dct_y[out.ID][:-1]))
        Cs.pop('H2O', None)
        out.set_flow_by_concentration(Q, Cs, units=('m3/d', 'mg/L'))


# %%

class HydraulicDelay(Pump):
    '''
    A fake unit for implementing hydraulic delay by a first-order reaction
    (i.e., a low-pass filter) with a specified time constant [d].

    See Also
    --------
    `Benchmark Simulation Model No.1 implemented in MATLAB & Simulink <https://www.cs.mcgill.ca/~hv/articles/WWTP/sim_manual.pdf>`
    '''
    def __init__(self, ID='', ins=None, outs=(), thermo=None, t_delay=1e-4, *,
                 init_with='WasteStream', F_BM_default=None, isdynamic=False):
        SanUnit.__init__(self, ID, ins, outs, thermo,
                         init_with=init_with, F_BM_default=F_BM_default,
                         isdynamic=isdynamic)
        self.t_delay = t_delay
        self._concs = None
        # self._q = None

    def set_init_conc(self, **kwargs):
        '''set the initial concentrations [mg/L].'''
        Cs = np.zeros(len(self.components))
        cmpx = self.components.index
        for k, v in kwargs.items(): Cs[cmpx(k)] = v
        self._concs = Cs

    def _init_state(self):
        '''initialize state by specifiying or calculating component concentrations
        based on influents. Total flow rate is always initialized as the sum of
        influent wastestream flows.'''
        self._state = self._collect_ins_state()[0]
        if self._concs is not None:
            self._state[:-1] = self._concs

    def _run(self):
        s_in, = self.ins
        s_out, = self.outs
        s_out.copy_like(s_in)

    def _compile_ODE(self):
        T = self.t_delay
        def dy_dt(t, QC_ins, QC, dQC_ins):
            dQC = self._dstate
            Q_in = QC_ins[0,-1]
            Q = QC[-1]
            C_in = QC_ins[0,:-1]
            C = QC[:-1]
            if dQC_ins[0,-1] == 0:
                dQC[-1] = 0
                dQC[:-1] = (Q_in*C_in - Q*C)/(Q*T)
            else:
                dQC[-1] = (Q_in - Q)/T
                dQC[:-1] = Q_in/Q*(C_in - C)/T
            self._update_dstate()
        self._ODE = dy_dt

    def _design(self):
        pass

    def _cost(self):
        pass


# %%

_hp_to_kW = auom('hp').conversion_factor('kW')
_lb_to_kg = auom('lb').conversion_factor('kg')
_ft_to_m = auom('ft').conversion_factor('m')
_ft3_to_gal = auom('ft3').conversion_factor('gallon')
_m3_to_gal = auom('m3').conversion_factor('gallon')

class WWTpump(SanUnit):
    '''
    Generic class for pumps used in wastewater treatment. [1]_

    Parameters
    ----------
    pump_type : str
        The type of the pump that determines the design algorithms to use.
        The following combination is valid:

            - "permeate_cross-flow"
            - "retentate_CSTR"
            - "retentate_AF"
            - "recirculation_CSTR"
            - "recirculation_AF"
            - "lift"
            - "sludge"
            - "chemical"

    Q_mgd : float
        Volumetric flow rate in million gallon per day, [mgd].
        Will use total volumetric flow through the unit if not provided.
    add_inputs : dict
        Additional inputs that will be passed to the corresponding design algorithm.
        Check the document for the design algorithm for the specific input requirements.

    References
    ----------
    .. [1] Shoener et al., Design of Anaerobic Membrane Bioreactors for the
        Valorization of Dilute Organic Carbon Waste Streams.
        Energy Environ. Sci. 2016, 9 (3), 1102–1112.
        https://doi.org/10.1039/C5EE03715H.
    '''
    _N_ins = 1
    _N_outs = 1

    v = 3 # fluid velocity, [ft/s]
    C = 110 # Hazen- Williams coefficient for stainless steel (SS)

    _default_equipment_lifetime = {'Pump': 15}

    _valid_pump_types = (
        'permeate_cross-flow',
        'retentate_CSTR',
        'retentate_AF',
        'recirculation_CSTR',
        'recirculation_AF',
        'lift',
        'sludge',
        'chemical'
        )


    def __init__(self, ID='', ins=None, outs=(), thermo=None,
                 init_with='WasteStream', isdynamic=False, *,
                 pump_type, Q_mgd=None, add_inputs):
        SanUnit.__init__(self, ID, ins, outs, thermo, init_with=init_with, isdynamic=isdynamic)
        self.pump_type = pump_type
        self.Q_mgd = Q_mgd
        self.add_inputs = add_inputs


    def _run(self):
        self.outs[0].copy_like(self.ins[0])


    def _design(self):

        pump_type = format_str(self.pump_type)
        design_func = getattr(self, f'design_{pump_type}')

        D = self.design_results
        pipe, pumps, hdpe = design_func()
        D['Pipe stainless steel [kg]'] = pipe
        #!!! need to consider pump's lifetime in LCA
        D['Pump stainless steel [kg]'] = pumps
        D['Chemical storage HDPE [m3]'] = hdpe


    def _cost(self):
        self.power_utility.rate = self.BHP/self.motor_efficiency * _hp_to_kW


    # Used by other classes
    @staticmethod
    def _batch_adding_pump(obj, IDs, ins_dct, type_dct, inputs_dct):
        for i in IDs:
            if not hasattr(obj, f'{i}_pump'):
                # if i == None:
                #     continue
                pump = WWTpump(
                    ID=f'{obj.ID}_{i}',
                    ins=ins_dct[i],
                    pump_type=type_dct[i],
                    add_inputs=inputs_dct[i])
                setattr(obj, f'{i}_pump', pump)


    # Generic algorithms that will be called by all design functions
    def _design_generic(self, Q_mgd, N_pump, L_s, L_d, H_ts, H_p):
        self.Q_mgd, self._H_ts, self._H_p = Q_mgd, H_ts, H_p
        v, C, Q_cfs = self.v, self.C, self.Q_cfs # [ft/s], -, [ft3/s]

        ### Suction side ###
        # Suction pipe (permeate header) dimensions
        OD_s, t_s, ID_s = select_pipe(Q_cfs/N_pump, v) # [in]

        # Suction friction head, [ft]
        self._H_sf = 3.02 * L_s * (v**1.85) * (C**(-1.85)) * ((ID_s/12)**(-1.17))

        ### Discharge side ###
        # Discharge pipe (permeate collector) dimensions
        OD_d, t_d, ID_d = select_pipe(Q_cfs, v)

        # Discharge friction head, [ft]
        self._H_df = 3.02 * L_d * (v**1.85) * (C**(-1.85)) * ((ID_d/12)**(-1.17))

        ### Material usage ###
        # Pipe SS, assume stainless steel, density = 0.29 lbs/in3
        # SS volume for suction, [in3]
        self._N_pump = N_pump
        V_s = N_pump * pi/4*((OD_s)**2-(ID_s)**2) * (L_s*12)
        # SS volume for discharge, [in3]
        V_d = pi/4*((OD_d)**2-(ID_d)**2) * (L_d*12)
        # Total SS mass, [kg]
        M_SS_pipe = 0.29 * (V_s+V_d) * _lb_to_kg

        # Pump SS (for pumps within 300-1000 gpm)
        # http://www.godwinpumps.com/images/uploads/ProductCatalog_Nov_2011_spread2.pdf
        # assume 50% of the product weight is SS
        M_SS_pump = N_pump * (725*0.5)

        return M_SS_pipe, M_SS_pump


    def design_permeate_cross_flow(self, Q_mgd=None, cas_per_tank=None, D_tank=None,
                                   TMP=None, include_aerobic_filter=False):
        '''
        Design pump for the permeate stream of cross-flow membrane configuration.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        cas_per_tank : int
            Number of membrane cassettes per tank.
        D_tank: float
            Depth of the membrane tank, [ft].
        TMP : float
            Transmembrane pressure, [psi].
        include_aerobic_filter : bool
            Whether aerobic filter is included in the reactor design.
        '''
        add_inputs = self.add_inputs
        Q_mgd = Q_mgd or self.Q_mgd
        cas_per_tank = cas_per_tank or add_inputs[0]
        D_tank = D_tank or add_inputs[1]
        TMP = TMP or add_inputs[2]
        include_aerobic_filter = include_aerobic_filter or add_inputs[3]

        H_ts_PERM = D_tank if include_aerobic_filter else 0

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=cas_per_tank,
            L_s=20, # based on a 30-module unit with a total length of 6 m, [ft]
            L_d=10*cas_per_tank, # based on a 30-module unit with a total width of 1.6 m and extra space, [ft]
            H_ts=H_ts_PERM, #  H_ds_PERM (D_tank) - H_ss_PERM (0 or D_tank)
            H_p=TMP*2.31 # TMP in water head, [ft], comment below on 2.31
            )

        # # factor = 2.31 calculated by
        # factor = auom('psi').conversion_factor('Pa') # Pa is kg/m/s2, now in [Pa]
        # factor /= 9.81 # divided by the standard gravity in m/s2, now in [kg/m2]
        # factor /= 1e3 # divided by water's density in kg/m3, now in [m]
        # factor *= auom('m').conversion_factor('ft') # m to ft

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_retentate_CSTR(self, Q_mgd=None, cas_per_tank=None):
        '''
        Design pump for the retent stream of CSTR reactors.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        cas_per_tank : int
            Number of membrane cassettes per tank.
        '''
        Q_mgd = Q_mgd or self.Q_mgd
        cas_per_tank = cas_per_tank or self.add_inputs[0]

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=cas_per_tank,
            L_s=100, # pipe length per module
            L_d=30, # pipe length per module (same as the discharge side of lift pump)
            H_ts=0., # H_ds_IR (D_tank) - H_ss_IR (D_tank)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_retentate_AF(self, Q_mgd=None, N_filter=None, D=None):
        '''
        Design pump for the retentate stream of AF reactors.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        N_filter : float
            Number of filter tanks.
        D : float
            Depth of the filter tank, [ft].
        '''
        add_inputs = self.add_inputs
        Q_mgd = Q_mgd or self.Q_mgd
        N_filter = N_filter or add_inputs[0]
        D = D or add_inputs[1]

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=N_filter,
            L_s=100, # assumed pipe length per filter, [ft]
            L_d=30, # same as discharge side of lift pumping, [ft]
            H_ts=0., # H_ds_IR (D) - H_ss_IR (D)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_recirculation_CSTR(self, Q_mgd=None, L_CSTR=None):
        '''
        Design pump for the recirculation stream of CSTR reactors.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        L_CSTR : float
            Length of the CSTR tank, [ft].
        '''
        Q_mgd = Q_mgd or self.Q_mgd
        L_CSTR = L_CSTR or self.add_inputs[0]

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=1,
            L_s=0., # ignore suction side
            L_d=L_CSTR, # pipe length per train
            H_ts=5., # H_ds_IR (5) - H_ss_IR (0)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_recirculation_AF(self, Q_mgd=None, N_filter=None, d=None,
                                D=None):
        '''
        Design pump for the recirculation stream of AF reactors.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        N_filter : float
            Number of filter tanks.
        d : float
            diameter of the filter tank, [ft].
        D : float
            Depth of the filter tank, [ft].
        '''
        add_inputs = self.add_inputs
        Q_mgd = Q_mgd or self.Q_mgd
        N_filter = N_filter or add_inputs[0]
        d = d or add_inputs[1]
        D = D or add_inputs[2]

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=N_filter,
            L_s=d+D, # pipe length per filter, [ft]
            L_d=30, # same as discharge side of lift pumping, [ft]
            H_ts=0., # H_ds_IR (D) - H_ss_IR (D)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_lift(self, Q_mgd=None, N_filter=None, D=None):
        '''
        Design pump for the filter tank to lift streams.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        N_filter : float
            Number of filter tanks.
        D : float
            Depth of the filter tank, [ft].
        '''
        add_inputs = self.add_inputs
        Q_mgd = Q_mgd or self.Q_mgd
        N_filter = N_filter or add_inputs[0]
        D = D or add_inputs[1]

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=N_filter,
            L_s=150, # length of suction pipe per filter, [ft]
            L_d=30, # pipe length per filter, [ft]
            H_ts=D, # H_ds_LIFT (D) - H_ss_LIFT (0)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_sludge(self, Q_mgd=None):
        '''
        Design pump for handling waste sludge.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        '''
        Q_mgd = Q_mgd or self.Q_mgd

        M_SS_IR_pipe, M_SS_IR_pump = self._design_generic(
            Q_mgd=Q_mgd,
            N_pump=1,
            L_s=50, # length of suction pipe, [ft]
            L_d=50, # length of discharge pipe, [ft]
            H_ts=0., # H_ds_LIFT (D) - H_ss_LIFT (0)
            H_p=0. # no pressure
            )

        return M_SS_IR_pipe, M_SS_IR_pump, 0


    def design_chemical(self, Q_mgd=None):
        '''
        Design pump for membrane cleaning chemicals (NaOCl and citric acid),
        storage containers are included, and are assumed to be cubic in shape
        and made of HDPE.

        Parameters defined through the `add_inputs` argument upon initiation of
        this unit (Q_mgd listed separatedly) will be used if not provided
        when calling this function.

        Parameters
        ----------
        Q_mgd : float
            Volumetric flow rate in million gallon per day, [mgd].
        '''
        if not Q_mgd:
            V_CHEM = self.ins[0].F_vol * 24 * 7 * 2 # for two weeks of storage, [m3]
            Q_CHEM_mgd = self.Q_mgd
        else:
            V_CHEM = (Q_mgd*1e6/_m3_to_gal) * 7 * 2
            Q_CHEM_mgd = Q_mgd

        # HDPE volume, [m3], 0.003 [m] is the thickness of the container
        V_HDPE = 0.003 * (V_CHEM**(1/3))**2*6
        # # Mass of HDPE, [m3], 950 is the density of the HDPE in [kg/m3]
        # M_HDPE = 950 * V_HDPE

        H_ss_CHEM = V_CHEM**(1/3) / _ft_to_m
        # 9'-7" is the water level in membrane trains
        # 18" is the distance from C/L of the pump to the ground
        H_ds_CHEM = 9 + 7/12 - 18/12
        H_ts_CHEM = H_ds_CHEM - H_ss_CHEM

        M_SS_CHEM_pipe, M_SS_CHEM_pump = self._design_generic(
            Q_mgd=Q_CHEM_mgd,
            N_pump=1,
            L_s=0., # no suction pipe
            L_d=30.,
            H_ts=H_ts_CHEM,
            H_p=0. # no pressure
            )

        return M_SS_CHEM_pipe, M_SS_CHEM_pump, V_HDPE


    @property
    def pump_type(self):
        '''
        [str] The type of the pump that determines the design algorithms to use.
        Use `valid_pump_type` to see acceptable pump types.
        '''
        return self._pump_type
    @pump_type.setter
    def pump_type(self, i):
        i_lower = i.lower()
        i_lower = i_lower.replace('cstr', 'CSTR')
        i_lower = i_lower.replace('af', 'AF')
        if i_lower not in self.valid_pump_types:
            raise ValueError(f'The given `pump_type` "{i}" is not valid, '
                             'check `valid_pump_types` for acceptable pump types.')
        self._pump_type = i_lower

    @property
    def valid_pump_types(self):
        '''[tuple] Acceptable pump types.'''
        return self._valid_pump_types

    @property
    def N_pump(self):
        '''[int] Number of pumps.'''
        return self._N_pump

    @property
    def H_sf(self):
        '''[float] Suction friction head, [ft].'''
        return self._H_sf

    @property
    def H_df(self):
        '''[float] Discharge friction head, [ft].'''
        return self._H_df

    @property
    def H_ts(self):
        '''[float] Total static head, [ft].'''
        return self._H_ts

    @property
    def H_p(self):
        '''[float] Pressure head, [ft].'''
        return self._H_p

    @property
    def TDH(self):
        '''[float] Total dynamic head, [ft].'''
        return self.H_ts+self.H_sf+self.H_df+self.H_p

    @property
    def BHP(self):
        '''[float] Brake horsepower, [hp].'''
        return (self.TDH*self.Q_gpm)/3960/self.brake_efficiency

    @property
    def Q_mgd(self):
        '''
        [float] Volumetric flow rate in million gallon per day, [mgd].
        Will use total volumetric flow through the unit if not provided.
        '''
        if self._Q_mgd:
            return self._Q_mgd
        return self.F_vol_in*_m3_to_gal*24/1e6
    @Q_mgd.setter
    def Q_mgd(self, i):
        self._Q_mgd = i

    @property
    def Q_gpm(self):
        '''[float] Volumetric flow rate in gallon per minute, [gpm].'''
        return self.Q_mgd*1e6/24/60

    @property
    def Q_cmd(self):
        '''
        [float] Volumetric flow rate in cubic meter per day, [cmd].
        '''
        return self.Q_mgd *1e6/_m3_to_gal # [m3/day]

    @property
    def Q_cfs(self):
        '''[float] Volumetric flow rate in cubic feet per second, [cfs].'''
        return self.Q_mgd*1e6/24/60/60/_ft3_to_gal

    @property
    def brake_efficiency(self):
        '''[float] Brake efficiency.'''
        return brake_eff(self.Q_gpm)

    @property
    def motor_efficiency(self):
        '''[float] Motor efficiency.'''
        return motor_eff(self.BHP)