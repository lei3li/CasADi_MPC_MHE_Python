#!/usr/bin/env python
# -*- coding: utf-8 -*-

import casadi as ca
import casadi.tools as ca_tools

import numpy as np
import time
from draw import Draw_MPC_tracking

def shift_movement(dT, t0, x0, u, current_states_series, f):
    """

    :param dT:Sampling time
    :param t0:Current time
    :param x0:Current state
    :param u:control series
    :param current_states_series:
    :param f:Dynamic model
    :return: t:new current timestep, st:next current state, u_end:control
    """
    f_value = f(x0, u[:, 0])
    # update the new current state
    current_state_new = x0 + dT*f_value.full()
    # update next time step
    current_t_new = t0 + dT
    # It shifts the control array (u) to the left, discarding the first control input and duplicating the last one.
    # This is done to prepare the control inputs for the next prediction horizon in the MPC loop
    shifted_control_series = np.concatenate((u[:, 1:], u[:, -1:]), axis=1)
    # It shifts the future states array (x_f) to the left, discarding the first state and duplicating the last one.
    # This is done to prepare the future states for the next prediction horizon in the MPC loop.
    shifted_states_series = np.concatenate((current_states_series[:, 1:], current_states_series[:, -1:]), axis=1)

    return current_t_new, current_state_new, shifted_control_series, shifted_states_series

def desired_command_and_trajectory(t, dt, x0_, N_):
    """
    Generates the desired state trajectory and control inputs for the Model Predictive Control (MPC) problem.
    :param t:Current time
    :param dt:Sampling interval
    :param x0_:Current state
    :param N_:Prediction horizon
    :return:
    """
    # initial state / last state
    x_ = x0_.reshape(1, -1).tolist()[0]
    u_ = []
    # states for the next N_ trajectories
    for i in range(N_):
        t_predict = t + dt*i
        x_ref_ = 0.5 * t_predict
        y_ref_ = 0.5 * t_predict
        theta_ref_ = 0.0
        v_ref_ = 0.5
        omega_ref_ = 0.0
        if x_ref_ >= 12.0:
            x_ref_ = 12.0
            v_ref_ = 0.0
        x_.append(x_ref_)
        x_.append(y_ref_)
        x_.append(theta_ref_)
        u_.append(v_ref_)
        u_.append(omega_ref_)
    # return pose and command
    x_ = np.array(x_).reshape(N_+1, -1)
    u_ = np.array(u_).reshape(N, -1)
    return u_, x_

if __name__ == '__main__':
    dt = 0.5 # sampling time [s]
    N = 8 # prediction horizon
    rob_diam = 0.3 # [m]
    v_max = 0.6
    omega_max = np.pi/4.0

    x = ca.SX.sym('x')
    y = ca.SX.sym('y')
    theta = ca.SX.sym('theta')
    states = ca.vertcat(x, y)
    states = ca.vertcat(states, theta)
    n_states = states.size()[0]

    v = ca.SX.sym('v')
    omega = ca.SX.sym('omega')
    controls = ca.vertcat(v, omega)
    n_controls = controls.size()[0]

    ## rhs
    rhs = ca.vertcat(v*ca.cos(theta), v*ca.sin(theta))
    rhs = ca.vertcat(rhs, omega)

    ## function
    f = ca.Function('f', [states, controls], [rhs], ['input_state', 'control_input'], ['rhs'])

    ## for MPC
    U = ca.SX.sym('U', n_controls, N)
    X = ca.SX.sym('X', n_states, N+1)
    U_ref = ca.SX.sym('U_ref', n_controls, N)
    X_ref = ca.SX.sym('X_ref', n_states, N+1)

    ### define
    Q = np.array([[1.0, 0.0, 0.0],[0.0, 5.0, 0.0],[0.0, 0.0, .1]])
    R = np.array([[0.5, 0.0], [0.0, 0.05]])
    #### cost function
    obj = 0 #### cost
    g = [] # equal constrains

    # ************************
    # State reference tracking
    # ************************
    g.append(X[:, 0]-X_ref[:, 0])

    for i in range(N):
        state_error_ = X[:, i] - X_ref[:, i+1]
        control_error_ = U[:, i] - U_ref[:, i]
        obj = obj + ca.mtimes([state_error_.T, Q, state_error_]) + ca.mtimes([control_error_.T, R, control_error_])
        x_next_ = f(X[:, i], U[:, i]) * dt + X[:, i]
        g.append(X[:, i+1]-x_next_)
    # First N control input, then N+1 state
    opt_variables = ca.vertcat( ca.reshape(U, -1, 1), ca.reshape(X, -1, 1))
    opt_params = ca.vertcat(ca.reshape(U_ref, -1, 1), ca.reshape(X_ref, -1, 1))

    nlp_prob = {'f': obj, 'x': opt_variables, 'p':opt_params, 'g':ca.vertcat(*g)}
    opts_setting = {'ipopt.max_iter':100, 'ipopt.print_level':0, 'print_time':0, 'ipopt.acceptable_tol':1e-8, 'ipopt.acceptable_obj_change_tol':1e-6}

    solver = ca.nlpsol('solver', 'ipopt', nlp_prob, opts_setting)

    lbg = 0.0
    ubg = 0.0
    lbx = []
    ubx = []
    for _ in range(N):
        lbx.append(-v_max)  # v_min
        lbx.append(-omega_max)  # omega_min
        ubx.append(v_max)
        ubx.append(omega_max)
    for _ in range(N+1): # note that this is different with the method using structure
        lbx.append(-20.0)
        lbx.append(-2.0)
        lbx.append(-np.inf)
        ubx.append(20.0)
        ubx.append(2.0)
        ubx.append(np.inf)

    # Simulation
    t0 = 0.0
    init_state = np.array([8.0, 0.0, 0.0]).reshape(-1, 1)  # initial state, used once
    current_state = init_state.copy()  # read initial state to current state
    u0 = np.array([0.0, 0.0]*N).reshape(-1, 2).T  # np.ones((N, 2))

    # We will update next_trajectories and next_states and next_controls after each iteration
    next_trajectories = np.tile(current_state.reshape(1, -1), N+1).reshape(N+1, -1)
    next_states = next_trajectories.copy()
    next_controls = np.zeros((N, 2))

    # History
    x_c = []  # contains for the history of the state
    u_c = []
    t_c = [t0]  # for the time
    desired_state_computed = []
    sim_time = 30.0

    ## start MPC
    mpciter = 0
    start_time = time.time()
    index_t = []
    while(mpciter - sim_time / dt < 0.0):
        current_time = mpciter * dt # current time
        ## set optimization parameter
        optimization_parameters = np.concatenate((next_controls.reshape(-1, 1), next_trajectories.reshape(-1, 1)))
        # print('{0}'.format(next_states))
        # print('{0}'.format(next_states.T.reshape(-1, 1)[:6]))
        # set initial guess of the optimization variables
        initial_guess = np.concatenate((u0.T.reshape(-1, 1), next_states.T.reshape(-1, 1)))
        t_ = time.time()
        # x0 is the initial guess for the decision variables. It provides a starting point for the optimization
        # algorithm.
        # p represents the parameters of the optimization problem that are treated as constants during
        # optimization but can be changed between solver calls without recompiling the problem.
        res = solver(x0=initial_guess, p=optimization_parameters, lbg=lbg, lbx=lbx, ubg=ubg, ubx=ubx)
        index_t.append(time.time()- t_)
        estimated_opt = res['x'].full() # the feedback is in the series [u0, x0, u1, x1, ...]
        # get action series
        u0 = estimated_opt[:int(n_controls*N)].reshape(N, n_controls).T  # (n_controls, N)
        # get states series
        x_m = estimated_opt[int(n_controls*N):].reshape(N+1, n_states).T  # [n_states, N + 1]
        x_c.append(x_m.T)
        u_c.append(u0[:, 0])
        t_c.append(t0)
        t0, current_state, u0, next_states = shift_movement(dt, t0, current_state, u0, x_m, f)
        current_state = ca.reshape(current_state, -1, 1)
        current_state = current_state.full()
        # print(current_state)
        desired_state_computed.append(current_state)
        next_controls, next_trajectories = desired_command_and_trajectory(t0, dt, current_state, N)
        mpciter = mpciter + 1
    t_v = np.array(index_t)
    print(t_v.mean())
    print((time.time() - start_time)/(mpciter))
    print(mpciter)
    draw_result = Draw_MPC_tracking(rob_diam=0.3, init_state=init_state, robot_states=desired_state_computed)