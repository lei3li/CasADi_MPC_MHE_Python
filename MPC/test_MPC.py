import casadi as ca

# Define decision variables
x = ca.MX.sym('x')
y = ca.MX.sym('y')

# Define a parameter
a = ca.MX.sym('a')

# Define the objective function with the parameter 'a'
objective = a*x**2 + y**2

# Define constraints
g = x + y - 1

# Define NLP
nlp = {'x': ca.vertcat(x, y), 'f': objective, 'g': g, 'p': a}  # Including 'p': a here

# Create an NLP solver instance
solver = ca.nlpsol('solver', 'ipopt', nlp)

# Solve the problem with different values of 'a'
for param_value in [1, 2, 3]:
    solution = solver(x0=[0, 0], p=param_value, lbg=0, ubg=0)  # 'p' argument specifies the parameter value
    print(f'Solution with a={param_value}:', solution['x'])
